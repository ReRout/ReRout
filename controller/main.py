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
from .cost_tracker import estimate_cost_from_response


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
    body { font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial; margin: 24px; }
    textarea, input, button { font-size: 14px; }
    textarea { width: 100%; height: 140px; }
    pre { background: #0b1220; color: #e5e7eb; padding: 12px; border-radius: 8px; overflow: auto; }
    .row { display: flex; gap: 8px; align-items: center; }
  </style>
</head>
<body>
  <h2>RouteLLM Playground</h2>
  <p>Leave model empty to auto-route via policy pipeline. Or specify a model like <code>openrouter/google/gemini-2.0-flash-exp:free</code>.</p>
  <div class='row'>
    <label for='model'>Model:</label>
    <input id='model' placeholder='(empty for auto-route)' style='width: 360px;' />
    <label><input type='checkbox' id='usePolicy' checked /> use routing_policy=task_router</label>
  </div>
  <p>
    <textarea id='prompt' placeholder='Type your prompt here...'>Write Python code to parse JSON</textarea>
  </p>
  <button id='send'>Send</button>
  <h3>Response</h3>
  <pre id='out'></pre>
  <script>
    const out = document.getElementById('out');
    document.getElementById('send').onclick = async () => {
      out.textContent = 'Loading...';
      const model = (document.getElementById('model').value || '').trim();
      const usePolicy = document.getElementById('usePolicy').checked;
      const body = {
        model: model,
        messages: [{ role: 'user', content: document.getElementById('prompt').value }]
      };
      if (!model && usePolicy) {
        body.extra_body = { routing_policy: 'task_router' };
      }
      try {
        const res = await fetch('/v1/chat/completions', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
        const text = await res.text();
        try { out.textContent = JSON.stringify(JSON.parse(text), null, 2); }
        catch { out.textContent = text; }
      } catch (e) {
        out.textContent = String(e);
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
    return {
        "status": "ok" if CONFIG and not CONFIG_LOAD_ERROR else "degraded",
        "config_error": CONFIG_LOAD_ERROR,
    }


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

        body: Dict[str, Any] = {
            "model": model_name,
            "messages": [m.model_dump() for m in request.messages],
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
                # Send routing_explain as first chunk in streaming mode
                if routing_explain:
                    explain_chunk = f"data: {json.dumps({'routing_explain': routing_explain})}\n\n"
                    yield explain_chunk
                
                async for chunk in stream_backend_chat_completions(backend, model_name, body):
                    yield chunk
            
            logger.info({"event": "orchestrator_request", "provider_model": resolved_model, "stream": True, "source": routing_explain.get("source") if routing_explain else "manual"})
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
        
        # Calculate and track cost
        cost_info: Optional[Dict[str, Any]] = None
        try:
            cost_info = estimate_cost_from_response(result, resolved_model)
            # Track metrics
            provider, model_name = parse_model(resolved_model)
            COST_COUNTER.labels(provider=provider, model=model_name).inc(cost_info["total_cost"])
            
            usage = result.get("usage", {})
            prompt_tokens = usage.get("prompt_tokens", 0)
            completion_tokens = usage.get("completion_tokens", 0)
            if prompt_tokens > 0:
                TOKEN_COUNTER.labels(type="prompt", provider=provider, model=model_name).inc(prompt_tokens)
            if completion_tokens > 0:
                TOKEN_COUNTER.labels(type="completion", provider=provider, model=model_name).inc(completion_tokens)
            
            # Add cost info to routing_explain
            if routing_explain is not None and isinstance(routing_explain, dict):
                routing_explain["cost"] = {
                    "total_cost_usd": cost_info["total_cost"],
                    "prompt_tokens": cost_info["prompt_tokens"],
                    "completion_tokens": cost_info["completion_tokens"],
                    "input_cost_usd": cost_info["input_cost"],
                    "output_cost_usd": cost_info["output_cost"],
                }
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
