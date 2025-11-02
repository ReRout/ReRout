# Sample API Wrapper - Example FastAPI App Using RouteLLM

This is a complete example of how to build a production API that uses RouteLLM for intelligent model routing.

## Features

- ✅ Simple, clean API interface
- ✅ Automatic model routing via RouteLLM
- ✅ Streaming support
- ✅ Cost tracking included
- ✅ Routing explanation in responses
- ✅ CORS enabled for web frontends

## Quick Start

### 1. Start RouteLLM

Make sure RouteLLM is running first:

```bash
# From project root
docker compose up -d

# Or run locally
python -m controller.main
```

### 2. Run Sample API

```bash
# Install dependencies
cd examples/sample-api
pip install -r requirements.txt

# Set RouteLLM URL (default: http://localhost:8084)
export ROUTELLM_URL=http://localhost:8084

# Run the sample API
python app.py
```

The API will start on http://localhost:9000

### 3. Test It

```bash
# Simple chat request
curl -X POST http://localhost:9000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [
      {"role": "user", "content": "Write Python code to parse JSON"}
    ],
    "use_auto_routing": true
  }'
```

**Response:**
```json
{
  "response": "...",
  "model_used": "openrouter/qwen/qwen3-coder:free",
  "routing_explain": {
    "source": "pipeline",
    "pipeline": {
      "intent": {"label": "code_generation", "confidence": 0.98},
      "complexity": {"level": "low", "confidence": 0.7},
      "policy": {"chosen": "openrouter/qwen/qwen3-coder:free"}
    },
    "cost": {
      "total_cost_usd": 0.0,
      "prompt_tokens": 15,
      "completion_tokens": 200
    }
  },
  "tokens_used": 215
}
```

## API Endpoints

### `GET /`
API information and available endpoints.

### `GET /health`
Health check - verifies RouteLLM connectivity.

### `POST /chat`
Chat completion with auto-routing.

**Request:**
```json
{
  "messages": [
    {"role": "user", "content": "Your prompt here"}
  ],
  "temperature": 1.0,
  "max_tokens": 500,
  "use_auto_routing": true
}
```

**Response:**
```json
{
  "response": "Model response...",
  "model_used": "openrouter/qwen/qwen3-coder:free",
  "routing_explain": {...},
  "cost": {...},
  "tokens_used": 215
}
```

### `POST /chat/stream`
Streaming chat completion (SSE format).

## Configuration

Set environment variables:

```bash
# RouteLLM URL (required)
export ROUTELLM_URL=http://localhost:8084

# RouteLLM API key (optional for local)
export ROUTELLM_API_KEY=your-key-here

# Sample API port (default: 9000)
export PORT=9000
```

## Use Cases

### 1. Simple Chat API

```python
import httpx

response = httpx.post("http://localhost:9000/chat", json={
    "messages": [{"role": "user", "content": "Hello!"}]
})
print(response.json()["response"])
```

### 2. Code Generation Assistant

```python
response = httpx.post("http://localhost:9000/chat", json={
    "messages": [
        {"role": "user", "content": "Write a Python function to sort a list"}
    ],
    "use_auto_routing": True  # Automatically routes to code-optimized model
})
```

### 3. With Streaming

```python
import httpx

with httpx.stream("POST", "http://localhost:9000/chat/stream", json={
    "messages": [{"role": "user", "content": "Tell me a story"}],
    "stream": True
}) as response:
    for line in response.iter_lines():
        if line.startswith("data: "):
            print(line[6:])  # Print content
```

## Integration Examples

### Python Client

```python
import httpx

class SampleAPIClient:
    def __init__(self, base_url="http://localhost:9000"):
        self.base_url = base_url
        self.client = httpx.AsyncClient()
    
    async def chat(self, message: str, **kwargs):
        response = await self.client.post(
            f"{self.base_url}/chat",
            json={
                "messages": [{"role": "user", "content": message}],
                **kwargs
            }
        )
        return response.json()
    
    async def close(self):
        await self.client.aclose()

# Usage
async def main():
    client = SampleAPIClient()
    result = await client.chat("Write Python code")
    print(result["response"])
    print(f"Model used: {result['model_used']}")
    await client.close()
```

### JavaScript/TypeScript

```typescript
async function chat(message: string) {
  const response = await fetch('http://localhost:9000/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      messages: [{ role: 'user', content: message }],
      use_auto_routing: true
    })
  });
  const data = await response.json();
  return data;
}
```

## Extending This Example

You can extend this sample API for:

1. **Authentication** - Add API key authentication
2. **Rate Limiting** - Add rate limits per user
3. **Caching** - Cache common requests
4. **Multi-tenancy** - Support multiple users/organizations
5. **Custom Routing** - Add your own routing logic
6. **Analytics** - Track usage, costs, etc.

## Next Steps

- See `examples/python-sdk/` for a Python SDK wrapper
- See `examples/web-demo/` for a full web application
- Check `README.md` in project root for RouteLLM setup

