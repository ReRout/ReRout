# RouteLLM Examples

This directory contains example applications demonstrating how to use RouteLLM.

## Available Examples

### 1. Sample API Wrapper (`sample-api/`)

A complete FastAPI application that wraps RouteLLM, demonstrating:
- How to integrate RouteLLM into your API
- Auto-routing usage
- Streaming support
- Error handling
- Cost tracking

**Quick Start:**
```bash
cd sample-api
pip install -r requirements.txt
export ROUTELLM_URL=http://localhost:8084
python app.py
```

See `sample-api/README.md` for details.

### 2. Python SDK (Coming Soon)

A clean Python SDK for RouteLLM with async support.

### 3. Web Demo (Coming Soon)

A React/Next.js chat application demonstrating RouteLLM.

### 4. Integration Examples (Coming Soon)

Common integration patterns:
- RAG (Retrieval Augmented Generation)
- Code assistant
- Chatbot
- Content generation

## Using Examples

All examples assume RouteLLM is running. Start it first:

```bash
# From project root
docker compose up -d
```

Then run any example from its directory.

## Contributing Examples

Have an interesting use case? Add it here!

1. Create a new directory under `examples/`
2. Include a `README.md` with setup instructions
3. Add to this index

