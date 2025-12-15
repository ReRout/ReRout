from __future__ import annotations

import json
import time
import logging
from typing import Any, Dict, List, Optional

import httpx
from fastapi import FastAPI, Header, HTTPException, Response
from pydantic import BaseModel
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from dotenv import load_dotenv
from fastapi.responses import HTMLResponse, StreamingResponse

from .backends import call_backend_chat_completions, stream_backend_chat_completions
from .config import ConfigError, load_config
from .router import parse_model, resolve_alias
from .cost_tracker import estimate_cost_from_response, calculate_cost_with_comparison, calculate_comparison_cost
from .memory_manager import TokenStackMemory


# Load .env (if present)
load_dotenv()

app = FastAPI(title="RouteLLM", version="0.1.0")

# Logging (JSON)
logger = logging.getLogger("orchestrator")
if not logger.handlers:
    from pythonjsonlogger import jsonlogger
    handler = logging.StreamHandler()
    formatter = jsonlogger.JsonFormatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

# Metrics
REQ_COUNTER = Counter("orchestrator_requests_total", "Total chat completion requests")
REQ_ERRORS = Counter("orchestrator_request_errors_total", "Chat completion errors")
LATENCY = Histogram("orchestrator_request_latency_seconds", "Chat completion latency seconds")
COST_COUNTER = Counter("orchestrator_cost_total", "Total cost in USD", ["provider", "model"])
TOKEN_COUNTER = Counter("orchestrator_tokens_total", "Total tokens", ["type", "provider", "model"])

try:
    CONFIG = load_config("config.yaml")
except ConfigError as e:
    CONFIG = None  # type: ignore
    CONFIG_LOAD_ERROR = str(e)
else:
    CONFIG_LOAD_ERROR = None

# Initialize memory manager
MEMORY_MANAGER: Optional[TokenStackMemory] = None
try:
    memory_config = (CONFIG.raw or {}).get("memory", {}) if CONFIG else {}
    if memory_config.get("enabled", False):
        # Try to initialize Redis if configured
        redis_client = None
        if memory_config.get("storage_backend") == "redis":
            try:
                import redis as redis_lib
                redis_url = memory_config.get("redis_url", "redis://localhost:6379")
                redis_client = redis_lib.from_url(redis_url, decode_responses=True)
                logger.info({"event": "redis_connected", "url": redis_url})
            except Exception as e:
                logger.warning({"event": "redis_connection_failed", "error": str(e), "fallback": "memory"})
        
        MEMORY_MANAGER = TokenStackMemory(
            max_tokens_per_conversation=memory_config.get("max_tokens_per_conversation", 4000),
            max_total_tokens=memory_config.get("max_total_tokens", 100000),
            pruning_strategy=memory_config.get("pruning_strategy", "fifo"),
            storage_backend=memory_config.get("storage_backend", "memory"),
            redis_client=redis_client
        )
        logger.info({"event": "memory_manager_initialized", "enabled": True})
    else:
        logger.info({"event": "memory_manager_disabled"})
except Exception as e:
    logger.error({"event": "memory_manager_init_failed", "error": str(e)})
    MEMORY_MANAGER = None


class Message(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    model: str
    messages: List[Message]
    temperature: Optional[float] = 1.0
    max_tokens: Optional[int] = None
    stream: Optional[bool] = False
    extra_body: Optional[Dict[str, Any]] = None


@app.get("/playground", response_class=HTMLResponse)
async def playground() -> str:
    return """
<!doctype html>
<html>
<head>
  <meta charset='utf-8' />
  <meta name='viewport' content='width=device-width, initial-scale=1' />
  <title>RouteLLM Playground</title>
  <style>
    body { font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial; margin: 24px; background: #f9fafb; }
    .container { max-width: 1200px; margin: 0 auto; background: white; padding: 24px; border-radius: 12px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
    h2 { margin-top: 0; color: #1f2937; }
    textarea, input, button, select { font-size: 14px; border: 1px solid #d1d5db; border-radius: 6px; padding: 8px; }
    textarea { width: 100%; height: 140px; font-family: monospace; }
    input[type="text"] { width: 300px; }
    input[type="checkbox"] { margin-right: 4px; }
    button { background: #3b82f6; color: white; border: none; padding: 10px 20px; cursor: pointer; font-weight: 500; }
    button:hover { background: #2563eb; }
    button:disabled { background: #9ca3af; cursor: not-allowed; }
    pre { background: #0b1220; color: #e5e7eb; padding: 12px; border-radius: 8px; overflow: auto; max-height: 500px; font-size: 12px; }
    .row { display: flex; gap: 12px; align-items: center; margin-bottom: 12px; flex-wrap: wrap; }
    .section { margin-bottom: 24px; padding: 16px; background: #f9fafb; border-radius: 8px; }
    .section h3 { margin-top: 0; color: #374151; font-size: 16px; }
    label { font-weight: 500; color: #374151; }
    .memory-info { background: #dbeafe; padding: 12px; border-radius: 6px; margin-top: 12px; font-size: 13px; }
    .memory-info strong { color: #1e40af; }
    .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; margin-top: 12px; }
    .stat-card { background: white; padding: 12px; border-radius: 6px; border: 1px solid #e5e7eb; }
    .stat-label { font-size: 12px; color: #6b7280; }
    .stat-value { font-size: 20px; font-weight: 600; color: #1f2937; }
  </style>
</head>
<body>
  <div class="container">
    <h2>🚀 RouteLLM Playground</h2>
    <p>Test automatic model routing and memory features. Leave model empty to auto-route via policy pipeline.</p>
    
    <div class="section">
      <h3>Configuration</h3>
      <div class="row">
        <label for='model'>Model:</label>
        <input id='model' placeholder='(empty for auto-route)' style='width: 360px;' />
        <label><input type='checkbox' id='usePolicy' checked /> Auto-routing</label>
      </div>
      
      <div class="row">
        <label><input type='checkbox' id='useMemory' /> Enable Memory</label>
        <label for='userId'>User ID:</label>
        <input id='userId' placeholder='user123' style='width: 150px;' />
        <label for='conversationId'>Conversation ID:</label>
        <input id='conversationId' placeholder='(auto-generated)' style='width: 150px;' />
      </div>
    </div>

    <div class="section">
      <h3>Chat</h3>
      <textarea id='prompt' placeholder='Type your prompt here...'>My name is Alice. I am a software engineer.</textarea>
      <div class="row" style="margin-top: 12px;">
        <button id='send'>Send</button>
        <button id='clearChat' style="background: #ef4444;">Clear Chat</button>
        <button id='refreshStats' style="background: #6b7280;">Refresh Memory Stats</button>
      </div>
    </div>

    <div class="section" id="memorySection" style="display: none;">
      <h3>📊 Memory Statistics</h3>
      <div id="memoryStats" class="memory-info">Loading...</div>
    </div>

    <div class="section">
      <h3>Response</h3>
      <pre id='out'>Ready to test...</pre>
    </div>
  </div>

  <script>
    const out = document.getElementById('out');
    const memorySection = document.getElementById('memorySection');
    const memoryStats = document.getElementById('memoryStats');
    let conversationId = null;

    // Load memory stats on page load
    async function loadMemoryStats() {
      try {
        const res = await fetch('/memory/stats');
        if (res.ok) {
          const data = await res.json();
          if (data.storage_backend) {
            memorySection.style.display = 'block';
            memoryStats.innerHTML = `
              <div class="stats">
                <div class="stat-card">
                  <div class="stat-label">Conversations</div>
                  <div class="stat-value">${data.total_conversations || 0}</div>
                </div>
                <div class="stat-card">
                  <div class="stat-label">Total Tokens</div>
                  <div class="stat-value">${data.total_tokens || 0}</div>
                </div>
                <div class="stat-card">
                  <div class="stat-label">Max per Conv</div>
                  <div class="stat-value">${data.max_tokens_per_conversation || 0}</div>
                </div>
                <div class="stat-card">
                  <div class="stat-label">Strategy</div>
                  <div class="stat-value" style="font-size: 14px;">${data.pruning_strategy || 'N/A'}</div>
                </div>
              </div>
              ${data.conversations && data.conversations.length > 0 ? 
                '<div style="margin-top: 12px;"><strong>Conversations:</strong><ul style="margin: 8px 0; padding-left: 20px;">' + 
                data.conversations.map(c => `<li>${c.id}: ${c.tokens} tokens, ${c.entries} entries</li>`).join('') + 
                '</ul></div>' : ''}
            `;
          }
        }
      } catch (e) {
        console.error('Failed to load memory stats:', e);
      }
    }

    // Check memory status
    async function checkMemoryStatus() {
      try {
        const res = await fetch('/health');
        const data = await res.json();
        if (data.memory && data.memory.enabled) {
          memorySection.style.display = 'block';
          loadMemoryStats();
        } else {
          memorySection.style.display = 'none';
        }
      } catch (e) {
        console.error('Failed to check memory status:', e);
      }
    }

    document.getElementById('refreshStats').onclick = loadMemoryStats;
    document.getElementById('send').onclick = async () => {
      const sendBtn = document.getElementById('send');
      sendBtn.disabled = true;
      out.textContent = 'Loading...';
      
      const model = (document.getElementById('model').value || '').trim();
      const usePolicy = document.getElementById('usePolicy').checked;
      const useMemory = document.getElementById('useMemory').checked;
      const userId = document.getElementById('userId').value.trim();
      const convId = document.getElementById('conversationId').value.trim() || conversationId;
      
      const body = {
        model: model,
        messages: [{ role: 'user', content: document.getElementById('prompt').value }]
      };
      
      body.extra_body = {};
      if (!model && usePolicy) {
        body.extra_body.routing_policy = 'task_router';
      }
      if (useMemory) {
        body.extra_body.use_memory = true;
        if (userId) body.extra_body.user_id = userId;
        if (convId) {
          body.extra_body.conversation_id = convId;
          conversationId = convId;
        }
      }
      
      try {
        const res = await fetch('/v1/chat/completions', { 
          method: 'POST', 
          headers: { 'Content-Type': 'application/json' }, 
          body: JSON.stringify(body) 
        });
        const text = await res.text();
        try { 
          const json = JSON.parse(text);
          out.textContent = JSON.stringify(json, null, 2);
          
          // Show response content if available
          if (json.choices && json.choices[0] && json.choices[0].message) {
            const content = json.choices[0].message.content;
            console.log('Response:', content);
          }
          
          // Refresh memory stats if memory is enabled
          if (useMemory) {
            setTimeout(loadMemoryStats, 500);
          }
        } catch { 
          out.textContent = text; 
        }
      } catch (e) {
        out.textContent = 'Error: ' + String(e);
      } finally {
        sendBtn.disabled = false;
      }
    };

    document.getElementById('clearChat').onclick = () => {
      out.textContent = 'Ready to test...';
      document.getElementById('prompt').value = '';
      if (conversationId) {
        fetch('/memory/clear', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ conversation_id: conversationId })
        }).then(() => {
          conversationId = null;
          loadMemoryStats();
        });
      }
    };

    // Initialize
    checkMemoryStatus();
    if (document.getElementById('useMemory').checked) {
      loadMemoryStats();
    }
    
    document.getElementById('useMemory').onchange = (e) => {
      if (e.target.checked) {
        checkMemoryStatus();
      } else {
        memorySection.style.display = 'none';
      }
    };
  </script>
</body>
</html>
    """


@app.get("/metrics")
async def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/health")
async def health() -> Dict[str, Any]:
    memory_stats = None
    if MEMORY_MANAGER:
        try:
            memory_stats = MEMORY_MANAGER.get_memory_stats()
        except Exception as e:
            logger.warning({"event": "memory_stats_failed", "error": str(e)})
    
    return {
        "status": "ok" if CONFIG and not CONFIG_LOAD_ERROR else "degraded",
        "config_error": CONFIG_LOAD_ERROR,
        "memory": {
            "enabled": MEMORY_MANAGER is not None,
            "stats": memory_stats
        } if memory_stats else {"enabled": MEMORY_MANAGER is not None}
    }


@app.post("/memory/clear")
async def clear_memory(
    conversation_id: str,
    authorization: Optional[str] = Header(default=None)
) -> Dict[str, Any]:
    """Clear memory for a specific conversation"""
    if not MEMORY_MANAGER:
        raise HTTPException(400, detail="Memory management is not enabled")
    
    MEMORY_MANAGER.clear_memory(conversation_id)
    return {"status": "cleared", "conversation_id": conversation_id}


@app.get("/memory/stats")
async def get_memory_stats(
    authorization: Optional[str] = Header(default=None)
) -> Dict[str, Any]:
    """Get memory statistics"""
    if not MEMORY_MANAGER:
        raise HTTPException(400, detail="Memory management is not enabled")
    
    return MEMORY_MANAGER.get_memory_stats()


async def run_pipeline(
    messages: List[Dict[str, Any]],
    pipeline_cfg: Dict[str, str],
    routing_rules: Dict[str, Any],
    policy_name: Optional[str],
) -> Dict[str, Any]:
    text = next((m.get("content", "") for m in reversed(messages) if m.get("role") == "user"), "")

    explain: Dict[str, Any] = {"pipeline": {}, "chosen": None}

    intent = {"label": "chatbot", "confidence": 0.5}
    complexity = {"level": "medium", "confidence": 0.5}

    async with httpx.AsyncClient(timeout=10.0) as client:
        # Intent
        intent_url = pipeline_cfg.get("intent_classifier")
        if intent_url:
            try:
                r = await client.post(intent_url, json={"text": text})
                r.raise_for_status()
                intent = r.json()
                explain["pipeline"]["intent"] = intent
            except Exception as e:
                explain["pipeline"]["intent_error"] = str(e)
        else:
            explain["pipeline"]["intent"] = intent

        # Complexity
        complexity_url = pipeline_cfg.get("complexity_estimator")
        if complexity_url:
            try:
                r = await client.post(complexity_url, json={"text": text})
                r.raise_for_status()
                complexity = r.json()
                explain["pipeline"]["complexity"] = complexity
            except Exception as e:
                explain["pipeline"]["complexity_error"] = str(e)
        else:
            explain["pipeline"]["complexity"] = complexity

        # Guardrails
        guard_url = pipeline_cfg.get("guardrails")
        if guard_url:
            try:
                r = await client.post(guard_url, json={"text": text})
                r.raise_for_status()
                guard = r.json()
                explain["pipeline"]["guardrails"] = guard
                if not guard.get("passed", True):
                    raise HTTPException(400, detail={"error": {"message": "Guardrails failed", "reasons": guard.get("reasons", [])}})
            except HTTPException:
                raise
            except Exception as e:
                explain["pipeline"]["guardrails_error"] = str(e)

        # Policy
        policy_url = pipeline_cfg.get("policy_engine")
        if policy_url:
            try:
                labels = {"intent": intent.get("label"), "complexity": complexity.get("level")}
                r = await client.post(policy_url, json={"labels": labels})
                r.raise_for_status()
                decision = r.json()
                explain["pipeline"]["policy"] = decision
                explain["chosen"] = decision.get("chosen")
                explain["source"] = "pipeline"
                return explain
            except Exception as e:
                explain["pipeline"]["policy_error"] = str(e)
        # If we get here, attempt routing_rules fallback when available
        if policy_name and isinstance(routing_rules, dict):
            policy_map = routing_rules.get(policy_name, {})
            chosen = policy_map.get(intent.get("label") or "chatbot")
            if chosen:
                explain["chosen"] = chosen
                explain["source"] = "routing_rules_fallback"
                return explain

    # Final default fallback
    explain["chosen"] = "mock/gpt-4o-mini"
    explain["source"] = "default_fallback"
    return explain


@app.post("/v1/chat/completions")
async def chat_completions(
    request: ChatRequest,
    authorization: Optional[str] = Header(default=None),
) -> Any:
    REQ_COUNTER.inc()
    start = time.perf_counter()
    routing_explain: Optional[Dict[str, Any]] = None
    resolved_model: Optional[str] = None
    try:
        if not CONFIG:
            raise HTTPException(500, detail=f"Config not loaded: {CONFIG_LOAD_ERROR}")

        provided_model = (request.model or "").strip()

        if not provided_model:
            pipeline_cfg = (CONFIG.raw or {}).get("pipeline", {})
            rules = (CONFIG.raw or {}).get("routing_rules", {})
            policy_name = None
            if request.extra_body and isinstance(request.extra_body, dict):
                policy_name = request.extra_body.get("routing_policy")
            routing_explain = await run_pipeline([m.model_dump() for m in request.messages], pipeline_cfg, rules, policy_name)
            chosen_model = routing_explain.get("chosen")
            if not chosen_model:
                raise HTTPException(400, detail="Auto-routing failed: no model could be chosen")
            resolved_model = chosen_model
        else:
            resolved_model = resolve_alias(provided_model, CONFIG)

        try:
            provider, model_name = parse_model(resolved_model)
        except ValueError as e:
            raise HTTPException(400, detail=str(e)) from e

        backend = CONFIG.get_backend_by_prefix(f"{provider}/")
        if not backend:
            raise HTTPException(404, detail=f"Provider '{provider}' not found")

        # Handle memory management
        messages_for_api = [m.model_dump() for m in request.messages]
        memory_enabled = False
        user_id = None
        conversation_id = None
        
        if request.extra_body and isinstance(request.extra_body, dict):
            memory_enabled = request.extra_body.get("use_memory", False)
            user_id = request.extra_body.get("user_id")
            conversation_id = request.extra_body.get("conversation_id")
        
        # If memory is enabled, get memory context
        if MEMORY_MANAGER and memory_enabled:
            messages_for_api = MEMORY_MANAGER.get_memory(
                messages=messages_for_api,
                user_id=user_id,
                conversation_id=conversation_id
            )
            logger.info({
                "event": "memory_retrieved",
                "conversation_id": conversation_id or "auto",
                "messages_count": len(messages_for_api),
                "original_messages_count": len(request.messages)
            })

        body: Dict[str, Any] = {
            "model": model_name,
            "messages": messages_for_api,
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "stream": request.stream,
        }

        if request.extra_body:
            for k, v in request.extra_body.items():
                if k not in body:
                    body[k] = v

        # Handle streaming responses
        if body.get("stream", False):
            async def generate_stream():
                # Track usage from streaming chunks
                prompt_tokens = 0
                completion_tokens = 0
                accumulated_content = ""
                
                # Estimate input tokens from messages (approx 4 chars per token)
                input_text = " ".join(m.get("content", "") for m in messages_for_api)
                estimated_prompt_tokens = max(len(input_text) // 4, 1)
                
                # Stream backend response
                async for chunk in stream_backend_chat_completions(backend, model_name, body):
                    yield chunk
                    
                    # Try to extract usage and content from chunk
                    if chunk.startswith("data: ") and not chunk.startswith("data: [DONE]"):
                        try:
                            chunk_data = json.loads(chunk[6:].strip())
                            if "usage" in chunk_data:
                                prompt_tokens = chunk_data["usage"].get("prompt_tokens", prompt_tokens)
                                completion_tokens = chunk_data["usage"].get("completion_tokens", completion_tokens)
                            # Accumulate content for token estimation
                            if "choices" in chunk_data and chunk_data["choices"]:
                                delta = chunk_data["choices"][0].get("delta", {})
                                if "content" in delta:
                                    accumulated_content += delta["content"]
                        except (json.JSONDecodeError, KeyError):
                            pass
                
                # If no usage data from provider, estimate tokens
                if prompt_tokens == 0:
                    prompt_tokens = estimated_prompt_tokens
                if completion_tokens == 0 and accumulated_content:
                    # Estimate output tokens (approx 4 chars per token)
                    completion_tokens = max(len(accumulated_content) // 4, 1)
                
                # Calculate cost with comparison after stream completes
                cost_info = calculate_cost_with_comparison(resolved_model, prompt_tokens, completion_tokens)
                
                # Build metadata payload
                metadata = {
                    "model": resolved_model,
                    "cost": {
                        "total_cost_usd": cost_info["total_cost"],
                        "prompt_tokens": cost_info["prompt_tokens"],
                        "completion_tokens": cost_info["completion_tokens"],
                    },
                    "comparison": cost_info["comparison"],
                }
                if routing_explain:
                    metadata["routing"] = {
                        "source": routing_explain.get("source"),
                        "chosen": routing_explain.get("chosen"),
                    }
                
                # Send metadata as content in a special format that frontend can parse
                metadata_marker = f"\n\n<!-- REROUT_META:{json.dumps(metadata)}:REROUT_META -->"
                yield f"data: {json.dumps({'choices': [{'delta': {'content': metadata_marker}}]})}\n\n"
            
            logger.info({"event": "orchestrator_request", "provider_model": resolved_model, "stream": True, "source": routing_explain.get("source") if routing_explain else "manual", "routing_explain": routing_explain})
            return StreamingResponse(
                generate_stream(),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "Connection": "keep-alive"}
            )

        # Non-streaming response
        response = await call_backend_chat_completions(backend, model_name, body)

        if response.status_code >= 400:
            try:
                payload = response.json()
            except json.JSONDecodeError:
                payload = {"error": {"message": response.text}}
            # Attach routing_explain and attempted model to the error payload
            if isinstance(payload, dict):
                payload.setdefault("routing_explain", routing_explain)
                payload.setdefault("attempted_model", resolved_model)
            raise HTTPException(status_code=response.status_code, detail=payload)

        result = response.json()
        
        # Add to memory if enabled
        if MEMORY_MANAGER and memory_enabled:
            try:
                MEMORY_MANAGER.add_to_memory(
                    messages=[m.model_dump() for m in request.messages],
                    response=result,
                    user_id=user_id,
                    conversation_id=conversation_id,
                    metadata={
                        "model": resolved_model,
                        "routing_source": routing_explain.get("source") if routing_explain else "manual"
                    }
                )
                logger.info({
                    "event": "memory_updated",
                    "conversation_id": conversation_id or "auto"
                })
            except Exception as e:
                logger.warning({"event": "memory_update_failed", "error": str(e)})
        
        # Calculate and track cost with comparison
        cost_info: Optional[Dict[str, Any]] = None
        try:
            usage = result.get("usage", {})
            prompt_tokens = usage.get("prompt_tokens", 0)
            completion_tokens = usage.get("completion_tokens", 0)
            
            cost_info = calculate_cost_with_comparison(resolved_model, prompt_tokens, completion_tokens)
            
            # Track metrics
            provider, model_name = parse_model(resolved_model)
            COST_COUNTER.labels(provider=provider, model=model_name).inc(cost_info["total_cost"])
            
            if prompt_tokens > 0:
                TOKEN_COUNTER.labels(type="prompt", provider=provider, model=model_name).inc(prompt_tokens)
            if completion_tokens > 0:
                TOKEN_COUNTER.labels(type="completion", provider=provider, model=model_name).inc(completion_tokens)
            
            # Add cost info with comparison to routing_explain
            if routing_explain is not None and isinstance(routing_explain, dict):
                routing_explain["cost"] = {
                    "total_cost_usd": cost_info["total_cost"],
                    "prompt_tokens": cost_info["prompt_tokens"],
                    "completion_tokens": cost_info["completion_tokens"],
                    "input_cost_usd": cost_info["input_cost"],
                    "output_cost_usd": cost_info["output_cost"],
                }
                routing_explain["comparison"] = cost_info["comparison"]
        except Exception as e:
            logger.warning({"event": "cost_calculation_failed", "error": str(e), "provider_model": resolved_model})
        
        if routing_explain is not None and isinstance(result, dict):
            result["routing_explain"] = routing_explain
        
        log_data = {
            "event": "orchestrator_request",
            "provider_model": resolved_model,
            "source": routing_explain.get("source") if routing_explain else "manual",
        }
        if cost_info:
            log_data["cost_usd"] = cost_info["total_cost"]
            log_data["tokens"] = cost_info["total_tokens"]
        logger.info(log_data)
        
        return result
    except HTTPException:
        REQ_ERRORS.inc()
        raise
    except Exception as e:
        REQ_ERRORS.inc()
        # Return structured error including attempted model and routing explain if any
        detail = {"error": {"message": str(e)}, "attempted_model": resolved_model, "routing_explain": routing_explain}
        raise HTTPException(500, detail=detail)
    finally:
        LATENCY.observe(time.perf_counter() - start)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8084)
