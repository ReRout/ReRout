from __future__ import annotations

import json
import time
import hashlib
import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from collections import deque

try:
    import tiktoken
    TIKTOKEN_AVAILABLE = True
except ImportError:
    TIKTOKEN_AVAILABLE = False
    logging.warning("tiktoken not available, using simple token estimation")

logger = logging.getLogger("memory_manager")


@dataclass
class MemoryEntry:
    """Single memory entry with tokens"""
    role: str
    content: str
    tokens: int
    timestamp: float
    metadata: Optional[Dict[str, Any]] = None


@dataclass
class ConversationMemory:
    """Memory for a single conversation"""
    conversation_id: str
    entries: List[MemoryEntry]
    total_tokens: int
    created_at: float
    last_accessed: float
    metadata: Dict[str, Any]


class TokenStackMemory:
    """
    Token-based memory manager that stacks conversation tokens.
    
    Features:
    - Stack tokens from conversations
    - Maintain token limits per conversation
    - Automatic pruning when limit exceeded
    - Multiple pruning strategies (FIFO, LIFO, importance-based)
    """
    
    def __init__(
        self,
        max_tokens_per_conversation: int = 4000,
        max_total_tokens: int = 100000,
        pruning_strategy: str = "fifo",
        storage_backend: str = "memory",  # "memory" or "redis"
        redis_client: Optional[Any] = None,
    ):
        """
        Initialize token-based memory manager.
        
        Args:
            max_tokens_per_conversation: Maximum tokens to keep per conversation
            max_total_tokens: Maximum total tokens across all conversations
            pruning_strategy: "fifo" (oldest first), "lifo" (newest first), "importance" (importance-based)
            storage_backend: "memory" (in-memory) or "redis" (persistent)
            redis_client: Redis client if using redis backend
        """
        self.max_tokens_per_conversation = max_tokens_per_conversation
        self.max_total_tokens = max_total_tokens
        self.pruning_strategy = pruning_strategy
        self.storage_backend = storage_backend
        
        # In-memory storage
        self.memories: Dict[str, ConversationMemory] = {}
        self.total_tokens = 0
        
        # Redis storage
        self.redis = redis_client
        
        # Token counting
        if TIKTOKEN_AVAILABLE:
            # Use cl100k_base (GPT-4/GPT-3.5 tokenizer)
            self.encoding = tiktoken.get_encoding("cl100k_base")
        else:
            self.encoding = None
        
        logger.info({
            "event": "memory_manager_initialized",
            "max_tokens_per_conv": max_tokens_per_conversation,
            "max_total_tokens": max_total_tokens,
            "pruning_strategy": pruning_strategy,
            "storage_backend": storage_backend,
            "tiktoken_available": TIKTOKEN_AVAILABLE
        })
    
    def _count_tokens(self, text: str) -> int:
        """Count tokens in text"""
        if self.encoding:
            return len(self.encoding.encode(text))
        else:
            # Simple estimation: ~4 characters per token
            return len(text) // 4
    
    def _get_conversation_id(self, messages: List[Dict[str, Any]], user_id: Optional[str] = None) -> str:
        """Generate conversation ID from messages or user_id"""
        if user_id:
            return f"user:{user_id}"
        
        # Generate from first user message
        if messages:
            first_user_msg = next((m for m in messages if m.get("role") == "user"), None)
            if first_user_msg:
                content = first_user_msg.get("content", "")
                return f"conv:{hashlib.sha256(content.encode()).hexdigest()[:16]}"
        
        # Fallback to timestamp
        return f"conv:{int(time.time())}"
    
    def _load_from_redis(self, conversation_id: str) -> Optional[ConversationMemory]:
        """Load conversation memory from Redis"""
        if not self.redis:
            return None
        
        try:
            data = self.redis.get(f"memory:{conversation_id}")
            if data:
                mem_dict = json.loads(data)
                # Reconstruct MemoryEntry objects
                entries = [
                    MemoryEntry(**entry) for entry in mem_dict["entries"]
                ]
                mem = ConversationMemory(
                    conversation_id=mem_dict["conversation_id"],
                    entries=entries,
                    total_tokens=mem_dict["total_tokens"],
                    created_at=mem_dict["created_at"],
                    last_accessed=mem_dict["last_accessed"],
                    metadata=mem_dict.get("metadata", {})
                )
                return mem
        except Exception as e:
            logger.error({"event": "redis_load_failed", "error": str(e), "conv_id": conversation_id})
        
        return None
    
    def _save_to_redis(self, memory: ConversationMemory):
        """Save conversation memory to Redis"""
        if not self.redis:
            return
        
        try:
            mem_dict = asdict(memory)
            # Convert entries to dict format
            mem_dict["entries"] = [asdict(entry) for entry in memory.entries]
            self.redis.setex(
                f"memory:{memory.conversation_id}",
                86400 * 7,  # 7 days TTL
                json.dumps(mem_dict)
            )
        except Exception as e:
            logger.error({"event": "redis_save_failed", "error": str(e), "conv_id": memory.conversation_id})
    
    def _prune_conversation(self, memory: ConversationMemory) -> ConversationMemory:
        """Prune conversation memory when token limit exceeded"""
        if memory.total_tokens <= self.max_tokens_per_conversation:
            return memory
        
        tokens_to_remove = memory.total_tokens - self.max_tokens_per_conversation
        removed_tokens = 0
        
        if self.pruning_strategy == "fifo":
            # Remove oldest entries first
            while removed_tokens < tokens_to_remove and memory.entries:
                entry = memory.entries.pop(0)
                removed_tokens += entry.tokens
                memory.total_tokens -= entry.tokens
        
        elif self.pruning_strategy == "lifo":
            # Remove newest entries first (keep oldest context)
            while removed_tokens < tokens_to_remove and memory.entries:
                entry = memory.entries.pop()
                removed_tokens += entry.tokens
                memory.total_tokens -= entry.tokens
        
        elif self.pruning_strategy == "importance":
            # Remove least important entries (simplified: remove assistant messages first)
            # Sort: user messages first (keep), then assistant (remove)
            user_entries = [e for e in memory.entries if e.role == "user"]
            assistant_entries = [e for e in memory.entries if e.role == "assistant"]
            
            # Keep all user messages, remove assistant messages if needed
            while removed_tokens < tokens_to_remove and assistant_entries:
                entry = assistant_entries.pop()
                removed_tokens += entry.tokens
                memory.total_tokens -= entry.tokens
                memory.entries.remove(entry)
            
            # If still over limit, remove oldest user messages
            while removed_tokens < tokens_to_remove and user_entries:
                entry = user_entries.pop(0)
                if entry in memory.entries:
                    removed_tokens += entry.tokens
                    memory.total_tokens -= entry.tokens
                    memory.entries.remove(entry)
        
        logger.info({
            "event": "memory_pruned",
            "conversation_id": memory.conversation_id,
            "removed_tokens": removed_tokens,
            "remaining_tokens": memory.total_tokens,
            "strategy": self.pruning_strategy
        })
        
        return memory
    
    def get_memory(
        self,
        messages: List[Dict[str, Any]],
        user_id: Optional[str] = None,
        conversation_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Get conversation memory with stacked tokens.
        
        Returns:
            List of messages with memory context included
        """
        # Get or generate conversation ID
        conv_id = conversation_id or self._get_conversation_id(messages, user_id)
        
        # Load memory
        if self.storage_backend == "redis":
            memory = self._load_from_redis(conv_id)
        else:
            memory = self.memories.get(conv_id)
        
        if not memory:
            # Create new memory
            memory = ConversationMemory(
                conversation_id=conv_id,
                entries=[],
                total_tokens=0,
                created_at=time.time(),
                last_accessed=time.time(),
                metadata={}
            )
        
        # Update last accessed
        memory.last_accessed = time.time()
        
        # Convert memory entries to message format
        memory_messages = [
            {"role": entry.role, "content": entry.content}
            for entry in memory.entries
        ]
        
        # Combine with current messages
        # If current messages already include history, just return them
        # Otherwise, prepend memory
        if messages and memory_messages:
            # Check if messages already have history
            if len(messages) == 1 and messages[0].get("role") == "user":
                # Single new message, prepend memory
                return memory_messages + messages
            else:
                # Messages already include some history, return as-is
                return messages
        
        return messages if not memory_messages else memory_messages + messages
    
    def add_to_memory(
        self,
        messages: List[Dict[str, Any]],
        response: Dict[str, Any],
        user_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """
        Add conversation to memory with token stacking.
        
        Args:
            messages: User messages from request
            response: LLM response
            user_id: Optional user identifier
            conversation_id: Optional conversation identifier
            metadata: Optional metadata to store
        """
        # Get or generate conversation ID
        conv_id = conversation_id or self._get_conversation_id(messages, user_id)
        
        # Load existing memory
        if self.storage_backend == "redis":
            memory = self._load_from_redis(conv_id)
        else:
            memory = self.memories.get(conv_id)
        
        if not memory:
            memory = ConversationMemory(
                conversation_id=conv_id,
                entries=[],
                total_tokens=0,
                created_at=time.time(),
                last_accessed=time.time(),
                metadata={}
            )
        
        # Add user messages
        for msg in messages:
            if msg.get("role") == "user":
                content = msg.get("content", "")
                tokens = self._count_tokens(content)
                entry = MemoryEntry(
                    role="user",
                    content=content,
                    tokens=tokens,
                    timestamp=time.time(),
                    metadata=msg.get("metadata")
                )
                memory.entries.append(entry)
                memory.total_tokens += tokens
        
        # Add assistant response
        if response.get("choices"):
            assistant_content = response["choices"][0].get("message", {}).get("content", "")
            if assistant_content:
                tokens = self._count_tokens(assistant_content)
                entry = MemoryEntry(
                    role="assistant",
                    content=assistant_content,
                    tokens=tokens,
                    timestamp=time.time(),
                    metadata=metadata or {}
                )
                memory.entries.append(entry)
                memory.total_tokens += tokens
        
        # Update metadata
        if metadata:
            memory.metadata.update(metadata)
        
        # Prune if needed
        memory = self._prune_conversation(memory)
        
        # Save memory
        if self.storage_backend == "redis":
            self._save_to_redis(memory)
        else:
            self.memories[conv_id] = memory
            self.total_tokens = sum(m.total_tokens for m in self.memories.values())
            
            # Prune old conversations if total tokens exceed limit
            if self.total_tokens > self.max_total_tokens:
                self._prune_oldest_conversations()
        
        logger.info({
            "event": "memory_updated",
            "conversation_id": conv_id,
            "total_tokens": memory.total_tokens,
            "entries_count": len(memory.entries)
        })
    
    def _prune_oldest_conversations(self):
        """Prune oldest conversations when total token limit exceeded"""
        # Sort by last accessed (oldest first)
        sorted_memories = sorted(
            self.memories.items(),
            key=lambda x: x[1].last_accessed
        )
        
        while self.total_tokens > self.max_total_tokens and sorted_memories:
            conv_id, memory = sorted_memories.pop(0)
            tokens_removed = memory.total_tokens
            del self.memories[conv_id]
            self.total_tokens -= tokens_removed
            
            logger.info({
                "event": "conversation_pruned",
                "conversation_id": conv_id,
                "tokens_removed": tokens_removed
            })
    
    def clear_memory(self, conversation_id: str):
        """Clear memory for a specific conversation"""
        if self.storage_backend == "redis":
            if self.redis:
                self.redis.delete(f"memory:{conversation_id}")
        else:
            if conversation_id in self.memories:
                tokens_removed = self.memories[conversation_id].total_tokens
                del self.memories[conversation_id]
                self.total_tokens -= tokens_removed
        
        logger.info({"event": "memory_cleared", "conversation_id": conversation_id})
    
    def get_memory_stats(self) -> Dict[str, Any]:
        """Get statistics about memory usage"""
        if self.storage_backend == "redis":
            # Would need to scan Redis keys
            return {"storage_backend": "redis", "stats": "not_available"}
        
        return {
            "storage_backend": "memory",
            "total_conversations": len(self.memories),
            "total_tokens": self.total_tokens,
            "max_total_tokens": self.max_total_tokens,
            "max_tokens_per_conversation": self.max_tokens_per_conversation,
            "pruning_strategy": self.pruning_strategy,
            "conversations": [
                {
                    "id": mem.conversation_id,
                    "tokens": mem.total_tokens,
                    "entries": len(mem.entries),
                    "last_accessed": mem.last_accessed
                }
                for mem in self.memories.values()
            ]
        }

