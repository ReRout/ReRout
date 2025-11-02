"""
Sample API Wrapper - Example FastAPI application using RouteLLM

This demonstrates how to build a production API that uses RouteLLM
for intelligent model routing behind the scenes.

Usage:
    python examples/sample-api/app.py
"""

from __future__ import annotations

import os
import logging
from typing import List, Optional, Dict, Any

import httpx
from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

app = FastAPI(
    title="Sample API Wrapper",
    description="Example API using RouteLLM for intelligent model routing",
    version="1.0.0",
)

# CORS middleware for web frontends
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify exact origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# RouteLLM configuration
ROUTELLM_URL = os.getenv("ROUTELLM_URL", "http://localhost:8084")
ROUTELLM_API_KEY = os.getenv("ROUTELLM_API_KEY", "")  # Optional for local

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("sample-api")


class Message(BaseModel):
    role: str = Field(..., description="Message role: 'user' or 'assistant'")
    content: str = Field(..., description="Message content")


class ChatRequest(BaseModel):
    messages: List[Message] = Field(..., description="Conversation messages")
    temperature: Optional[float] = Field(1.0, ge=0.0, le=2.0, description="Sampling temperature")
    max_tokens: Optional[int] = Field(None, gt=0, description="Maximum tokens to generate")
    stream: Optional[bool] = Field(False, description="Stream response")
    use_auto_routing: Optional[bool] = Field(
        True,
        description="Use RouteLLM auto-routing (if False, specify model in messages)"
    )


class ChatResponse(BaseModel):
    response: str
    model_used: str = Field(..., description="Model that was used for this request")
    routing_explain: Optional[Dict[str, Any]] = None
    cost: Optional[Dict[str, Any]] = None
    tokens_used: Optional[int] = None
    
    model_config = {"protected_namespaces": ()}


class HealthResponse(BaseModel):
    status: str
    routellm_available: bool


async def call_routellm(
    messages: List[Dict[str, str]],
    temperature: float = 1.0,
    max_tokens: Optional[int] = None,
    stream: bool = False,
    use_auto_routing: bool = True,
) -> Dict[str, Any]:
    """Call RouteLLM API with proper error handling."""
    url = f"{ROUTELLM_URL}/v1/chat/completions"
    
    headers = {"Content-Type": "application/json"}
    if ROUTELLM_API_KEY:
        headers["Authorization"] = f"Bearer {ROUTELLM_API_KEY}"
    
    body: Dict[str, Any] = {
        "model": "",  # Empty for auto-routing
        "messages": messages,
        "temperature": temperature,
        "stream": stream,
    }
    
    if max_tokens:
        body["max_tokens"] = max_tokens
    
    if use_auto_routing:
        body["extra_body"] = {"routing_policy": "task_router"}
    else:
        # If not auto-routing, expect model in first message or use default
        body["model"] = "openrouter/minimax/minimax-m2:free"
    
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(url, json=body, headers=headers)
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as e:
        error_detail = e.response.json() if e.response.headers.get("content-type", "").startswith("application/json") else {"error": e.response.text}
        logger.error({"event": "routellm_error", "status": e.response.status_code, "detail": error_detail})
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"RouteLLM error: {error_detail}"
        )
    except httpx.RequestError as e:
        logger.error({"event": "routellm_connection_error", "error": str(e)})
        raise HTTPException(status_code=503, detail=f"Cannot connect to RouteLLM: {str(e)}")


@app.get("/", tags=["Root"])
async def root():
    """Root endpoint with API information."""
    return {
        "name": "Sample API Wrapper",
        "description": "Example API using RouteLLM for intelligent model routing",
        "routellm_url": ROUTELLM_URL,
        "endpoints": {
            "/chat": "POST - Chat completion with auto-routing",
            "/health": "GET - Health check",
        },
    }


@app.get("/health", response_model=HealthResponse, tags=["Health"])
async def health():
    """Health check endpoint."""
    routellm_available = False
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{ROUTELLM_URL}/health")
            routellm_available = response.status_code == 200
    except Exception:
        pass
    
    return HealthResponse(
        status="ok" if routellm_available else "degraded",
        routellm_available=routellm_available,
    )


@app.post("/chat", response_model=ChatResponse, tags=["Chat"])
async def chat(request: ChatRequest):
    """
    Chat completion endpoint with automatic model routing.
    
    This endpoint uses RouteLLM to automatically select the best model
    based on the prompt's intent and complexity.
    """
    # Convert messages to dict format
    messages_dict = [{"role": msg.role, "content": msg.content} for msg in request.messages]
    
    # Call RouteLLM
    result = await call_routellm(
        messages=messages_dict,
        temperature=request.temperature,
        max_tokens=request.max_tokens,
        stream=request.stream,
        use_auto_routing=request.use_auto_routing,
    )
    
    # Extract response
    choices = result.get("choices", [])
    if not choices:
        raise HTTPException(status_code=500, detail="No response from RouteLLM")
    
    message = choices[0].get("message", {})
    response_text = message.get("content", "")
    model_used = result.get("model", "unknown")
    
    # Extract routing explanation
    routing_explain = result.get("routing_explain")
    
    # Extract cost information
    cost = None
    if routing_explain and isinstance(routing_explain, dict):
        cost = routing_explain.get("cost")
    
    # Extract usage
    usage = result.get("usage", {})
    tokens_used = usage.get("total_tokens")
    
    logger.info({
        "event": "chat_request",
        "model_used": model_used,
        "tokens_used": tokens_used,
        "auto_routing": request.use_auto_routing,
    })
    
    return ChatResponse(
        response=response_text,
        model_used=model_used,
        routing_explain=routing_explain,
        cost=cost,
        tokens_used=tokens_used,
    )


@app.post("/chat/stream", tags=["Chat"])
async def chat_stream(request: ChatRequest):
    """
    Streaming chat completion endpoint.
    
    Returns Server-Sent Events (SSE) stream of the response.
    """
    from fastapi.responses import StreamingResponse
    
    messages_dict = [{"role": msg.role, "content": msg.content} for msg in request.messages]
    
    async def generate():
        url = f"{ROUTELLM_URL}/v1/chat/completions"
        headers = {"Content-Type": "application/json"}
        if ROUTELLM_API_KEY:
            headers["Authorization"] = f"Bearer {ROUTELLM_API_KEY}"
        
        body: Dict[str, Any] = {
            "model": "",
            "messages": messages_dict,
            "temperature": request.temperature,
            "stream": True,
        }
        if request.max_tokens:
            body["max_tokens"] = request.max_tokens
        if request.use_auto_routing:
            body["extra_body"] = {"routing_policy": "task_router"}
        
        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream("POST", url, json=body, headers=headers) as response:
                response.raise_for_status()
                async for chunk in response.aiter_text():
                    if chunk:
                        yield chunk
    
    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"}
    )


if __name__ == "__main__":
    import uvicorn
    
    port = int(os.getenv("PORT", "9000"))
    uvicorn.run(app, host="0.0.0.0", port=port)

