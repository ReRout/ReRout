# Token-Based Memory Usage Guide

## Overview

RouteLLM now supports token-based memory stacking, allowing conversations to maintain context across multiple requests. This enables personalized, context-aware interactions.

## How It Works

### Token Stacking
- Each conversation maintains a stack of messages (tokens)
- Tokens are counted using tiktoken (GPT-4/GPT-3.5 tokenizer)
- Memory is automatically pruned when token limits are exceeded
- Supports multiple pruning strategies

### Pruning Strategies

1. **FIFO (First In, First Out)** - Default
   - Removes oldest messages first
   - Preserves recent context

2. **LIFO (Last In, First Out)**
   - Removes newest messages first
   - Preserves original context

3. **Importance-Based**
   - Keeps all user messages
   - Removes assistant messages first
   - Fallback to FIFO if still over limit

## Configuration

### Enable Memory in `config.yaml`

```yaml
memory:
  enabled: true
  max_tokens_per_conversation: 4000
  max_total_tokens: 100000
  pruning_strategy: "fifo"
  storage_backend: "memory"  # or "redis"
  redis_url: "redis://localhost:6379"
```

### Using Memory in Requests

Enable memory per request using `extra_body`:

```python
import requests

response = requests.post(
    "http://localhost:8084/v1/chat/completions",
    json={
        "model": "",
        "messages": [
            {"role": "user", "content": "My name is Alice"}
        ],
        "extra_body": {
            "use_memory": True,
            "user_id": "user123",  # Optional: for user-specific memory
            "conversation_id": "conv456",  # Optional: for conversation-specific memory
            "routing_policy": "task_router"
        }
    }
)
```

## Examples

### Example 1: Basic Conversation with Memory

```python
import requests

base_url = "http://localhost:8084/v1/chat/completions"

# First message
response1 = requests.post(
    base_url,
    json={
        "model": "",
        "messages": [{"role": "user", "content": "My name is Alice. I'm a software engineer."}],
        "extra_body": {
            "use_memory": True,
            "user_id": "alice123"
        }
    }
)
print(response1.json()["choices"][0]["message"]["content"])

# Second message - remembers name and profession
response2 = requests.post(
    base_url,
    json={
        "model": "",
        "messages": [{"role": "user", "content": "What's my profession?"}],
        "extra_body": {
            "use_memory": True,
            "user_id": "alice123"
        }
    }
)
# Response will include context from first message
print(response2.json()["choices"][0]["message"]["content"])
```

### Example 2: Conversation-Specific Memory

```python
# Start a new conversation
response1 = requests.post(
    base_url,
    json={
        "model": "",
        "messages": [{"role": "user", "content": "I'm working on a Python project"}],
        "extra_body": {
            "use_memory": True,
            "conversation_id": "python-project-1"
        }
    }
)

# Continue same conversation
response2 = requests.post(
    base_url,
    json={
        "model": "",
        "messages": [{"role": "user", "content": "What framework should I use?"}],
        "extra_body": {
            "use_memory": True,
            "conversation_id": "python-project-1"
        }
    }
)
# Response will remember "Python project" context
```

### Example 3: Using cURL

```bash
# First request
curl -X POST http://localhost:8084/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "",
    "messages": [{"role": "user", "content": "I like Python"}],
    "extra_body": {
      "use_memory": true,
      "user_id": "user123"
    }
  }'

# Second request - remembers preference
curl -X POST http://localhost:8084/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "",
    "messages": [{"role": "user", "content": "What programming language do I like?"}],
    "extra_body": {
      "use_memory": true,
      "user_id": "user123"
    }
  }'
```

## API Endpoints

### Check Memory Status

```bash
curl http://localhost:8084/health
```

Response includes memory status:
```json
{
  "status": "ok",
  "memory": {
    "enabled": true,
    "stats": {
      "total_conversations": 5,
      "total_tokens": 15000,
      "max_total_tokens": 100000
    }
  }
}
```

### Get Memory Statistics

```bash
curl http://localhost:8084/memory/stats
```

### Clear Conversation Memory

```bash
curl -X POST http://localhost:8084/memory/clear \
  -H "Content-Type: application/json" \
  -d '{"conversation_id": "conv123"}'
```

## Storage Backends

### In-Memory (Default)
- Fast, no dependencies
- Lost on restart
- Good for development/testing

### Redis (Persistent)
- Persistent across restarts
- Supports distributed deployments
- Requires Redis server

```yaml
memory:
  enabled: true
  storage_backend: "redis"
  redis_url: "redis://localhost:6379"
```

## Token Limits

### Per Conversation
- Default: 4000 tokens
- Configurable in `config.yaml`
- Automatically pruned when exceeded

### Total Memory
- Default: 100,000 tokens across all conversations
- Oldest conversations pruned first
- Prevents memory exhaustion

## Best Practices

1. **Use user_id for user-specific memory**
   - Enables personalized experiences
   - Memory persists across sessions

2. **Use conversation_id for session-specific memory**
   - Good for temporary conversations
   - Can be cleared independently

3. **Set appropriate token limits**
   - Balance context vs. cost
   - More tokens = better context but higher costs

4. **Choose pruning strategy**
   - FIFO: Good for most use cases
   - Importance: Good for preserving user context
   - LIFO: Good for preserving original context

5. **Monitor memory usage**
   - Check `/health` endpoint
   - Monitor `/memory/stats`
   - Adjust limits as needed

## Troubleshooting

### Memory Not Working
- Check `memory.enabled: true` in config.yaml
- Verify memory manager initialized (check logs)
- Ensure `use_memory: true` in request

### Memory Growing Too Large
- Reduce `max_tokens_per_conversation`
- Reduce `max_total_tokens`
- Use more aggressive pruning strategy

### Redis Connection Issues
- Check Redis is running
- Verify `redis_url` in config
- Falls back to in-memory if Redis unavailable

## Integration with DeepMemory

This token-based memory system can be integrated with DeepMemory:
- Use DeepMemory for long-term user profiles
- Use token stacking for conversation context
- Combine both for best personalization

