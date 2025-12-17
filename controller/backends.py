from __future__ import annotations

import os
import time
import json
import asyncio
from typing import Any, Dict, AsyncGenerator

import httpx


async def call_backend_chat_completions(
    backend: Dict[str, Any],
    model_name: str,
    body: Dict[str, Any],
) -> httpx.Response:
    # Mock mode for local testing without API keys or network calls
    if backend.get("mock", False):
        # Minimal OpenAI-compatible response shape
        content = {
            "id": f"chatcmpl-mock-{int(time.time())}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model_name,
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": f"[MOCK:{backend.get('name','mock')}] Echo: "
                                   f"{body.get('messages', [{'content': ''}])[-1].get('content', '')}",
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }
        return httpx.Response(status_code=200, content=json.dumps(content), headers={"Content-Type": "application/json"})

    base_url: str = backend["base_url"].rstrip("/")
    url = f"{base_url}/chat/completions"

    headers: Dict[str, str] = {"Content-Type": "application/json"}

    if backend.get("require_api_key", True):
        api_key_env = backend.get("api_key_env")
        if not api_key_env:
            raise RuntimeError("Backend requires API key but 'api_key_env' not set")
        api_key = os.getenv(api_key_env)
        if not api_key:
            raise RuntimeError(f"Environment variable {api_key_env} is not set")
        headers["Authorization"] = f"Bearer {api_key}"

    # Remove unsupported params if defined
    unsupported = set(backend.get("unsupported_params", []) or [])
    filtered = {k: v for k, v in body.items() if k not in unsupported}

    filtered["model"] = model_name

    # OpenRouter requires HTTP-Referer header
    if "openrouter" in backend.get("base_url", "").lower():
        headers["HTTP-Referer"] = os.getenv("HTTP_REFERER", "http://localhost:8084")
        headers["X-Title"] = os.getenv("X_TITLE", "RouteLLM")

    # Retry logic with exponential backoff
    max_attempts = 3
    for attempt in range(max_attempts):
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(url, json=filtered, headers=headers)
                response.raise_for_status()
                return response
        except (httpx.HTTPStatusError, httpx.RequestError, httpx.TimeoutException) as e:
            if attempt == max_attempts - 1:
                raise  # Last attempt, re-raise
            wait_time = min(2 ** attempt, 10)  # Exponential backoff, max 10s
            await asyncio.sleep(wait_time)
            continue


async def stream_backend_chat_completions(
    backend: Dict[str, Any],
    model_name: str,
    body: Dict[str, Any],
) -> AsyncGenerator[str, None]:
    """Stream responses from backend."""
    # Mock mode for local testing
    if backend.get("mock", False):
        mock_content = f"[MOCK:{backend.get('name','mock')}] Echo: {body.get('messages', [{'content': ''}])[-1].get('content', '')}"
        # Emulate SSE format
        chunks = [f"data: {json.dumps({'choices': [{'delta': {'content': c}}]})}\n\n" for c in mock_content]
        chunks.append("data: [DONE]\n\n")
        for chunk in chunks:
            yield chunk
            await asyncio.sleep(0.01)  # Small delay for realism
        return

    base_url: str = backend["base_url"].rstrip("/")
    url = f"{base_url}/chat/completions"

    headers: Dict[str, str] = {"Content-Type": "application/json"}

    if backend.get("require_api_key", True):
        api_key_env = backend.get("api_key_env")
        if not api_key_env:
            error_msg = "Backend requires API key but 'api_key_env' not set"
            yield f"data: {json.dumps({'error': {'message': error_msg, 'type': 'configuration_error'}})}\n\n"
            yield "data: [DONE]\n\n"
            return
        api_key = os.getenv(api_key_env)
        if not api_key:
            error_msg = f"Environment variable {api_key_env} is not set"
            yield f"data: {json.dumps({'error': {'message': error_msg, 'type': 'configuration_error'}})}\n\n"
            yield "data: [DONE]\n\n"
            return
        headers["Authorization"] = f"Bearer {api_key}"

    # Remove unsupported params if defined
    unsupported = set(backend.get("unsupported_params", []) or [])
    filtered = {k: v for k, v in body.items() if k not in unsupported}

    filtered["model"] = model_name

    # OpenRouter requires HTTP-Referer header (add here too for streaming)
    if "openrouter" in backend.get("base_url", "").lower():
        headers.setdefault("HTTP-Referer", os.getenv("HTTP_REFERER", "http://localhost:8084"))
        headers.setdefault("X-Title", os.getenv("X_TITLE", "RouteLLM"))
    
    # Retry logic for streaming with graceful error handling
    max_attempts = 3
    last_error = None
    for attempt in range(max_attempts):
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                async with client.stream("POST", url, json=filtered, headers=headers) as response:
                    # Check for HTTP errors before streaming
                    if response.status_code >= 400:
                        error_body = await response.aread()
                        try:
                            error_json = json.loads(error_body)
                            error_msg = error_json.get("error", {}).get("message", str(error_body))
                        except (json.JSONDecodeError, AttributeError):
                            error_msg = error_body.decode("utf-8", errors="replace")
                        
                        # Handle rate limiting specifically
                        if response.status_code == 429:
                            if attempt < max_attempts - 1:
                                wait_time = min(2 ** (attempt + 1), 10)
                                await asyncio.sleep(wait_time)
                                continue
                            error_msg = f"Rate limited by {backend.get('name', 'provider')}. Please wait a moment and try again. ({error_msg})"
                        
                        # Yield error as SSE message with content so frontend displays it
                        error_content = f"⚠️ **Error from {backend.get('name', 'provider')}**: {error_msg}"
                        yield f"data: {json.dumps({'choices': [{'delta': {'content': error_content}}]})}\n\n"
                        yield "data: [DONE]\n\n"
                        return
                    
                    async for chunk in response.aiter_text():
                        if chunk:
                            yield chunk
                    return  # Success, exit retry loop
        except httpx.TimeoutException as e:
            last_error = f"Request timed out after 120 seconds"
            if attempt < max_attempts - 1:
                wait_time = min(2 ** attempt, 10)
                await asyncio.sleep(wait_time)
                continue
        except httpx.RequestError as e:
            last_error = f"Network error: {str(e)}"
            if attempt < max_attempts - 1:
                wait_time = min(2 ** attempt, 10)
                await asyncio.sleep(wait_time)
                continue
        except Exception as e:
            last_error = str(e)
            if attempt < max_attempts - 1:
                wait_time = min(2 ** attempt, 10)
                await asyncio.sleep(wait_time)
                continue
    
    # All retries exhausted - yield error as content
    error_content = f"⚠️ **Error**: {last_error or 'Unknown error occurred'}"
    yield f"data: {json.dumps({'choices': [{'delta': {'content': error_content}}]})}\n\n"
    yield "data: [DONE]\n\n"
