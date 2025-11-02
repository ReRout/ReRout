# RouteLLM v2 - Project Structure

## Overview

RouteLLM is a production-ready LLM router with microservices architecture, automatic model selection, cost tracking, and comprehensive observability.

## Current Architecture

```
routellm-v2/
├── config.yaml                 # Main configuration (backends, routing rules, pipeline)
├── config.example.yaml         # Example configuration template
├── docker-compose.yml          # Multi-service Docker setup
├── Dockerfile                  # Base image for all services
├── requirements.txt            # Python dependencies
├── Makefile                    # Development commands
├── .env                        # Environment variables (API keys, ONNX paths)
├── .gitignore                  # Git ignore rules
│
├── controller/                 # Main orchestrator service (port 8084)
│   ├── __init__.py
│   ├── main.py                # FastAPI app - entry point
│   ├── router.py               # Routing logic (prefix, aliases)
│   ├── backends.py             # Backend integrations (OpenAI, Anthropic, etc.)
│   ├── config.py               # Config loading and validation
│   └── cost_tracker.py         # Cost calculation and tracking
│
├── classifiers/               # ML classification microservices
│   ├── intent/
│   │   └── app.py             # Intent classifier (port 8000)
│   │                          # - ONNX-based (DistilBERT) or heuristic
│   │                          # - Classifies: code_generation, reasoning, etc.
│   │
│   └── complexity/
│       └── app.py             # Complexity estimator (port 8001)
│                              # - ONNX-based (Logistic Regression) or heuristic
│                              # - Classifies: low, medium, high
│
├── guardrails/                # Safety and compliance microservice
│   └── app.py                 # Guardrails service (port 8002)
│                              # - PII detection (SSN, email, phone, credit card, API keys)
│                              # - Content filtering
│                              # - Prometheus metrics
│
├── policy_engine/             # Routing decision microservice
│   └── app.py                 # Policy engine (port 8003)
│                              # - Model selection based on intent/complexity
│                              # - A/B testing support
│                              # - Epsilon-greedy bandit algorithm
│                              # - Cost tier management
│
├── cli/                       # Command-line tool
│   └── routellm.py            # CLI for interacting with router
│
├── monitoring/                # Observability stack
│   ├── prometheus.yml         # Prometheus scrape configuration
│   ├── grafana-dashboard.json # Grafana dashboard definition
│   ├── grafana-setup-guide.md # Grafana setup instructions
│   └── README.md              # Monitoring documentation
│
├── tests/                     # Test suite
│   └── test_basic.py          # Basic integration tests
│
├── scripts/                   # Utility scripts
│   └── kill_ports.sh          # Kill processes on common ports
│
├── intent_onnx/               # ONNX model files for intent classification
│   ├── model.onnx
│   ├── tokenizer.json
│   └── config.json
│
└── complexity_onnx/           # ONNX model files for complexity estimation
    └── model.onnx
```

## Service Ports

| Service | Port | Endpoint | Description |
|---------|------|----------|-------------|
| Controller | 8084 | `/v1/chat/completions` | Main API endpoint |
| Intent Classifier | 8000 | `/classify` | Intent classification |
| Complexity Estimator | 8001 | `/classify` | Complexity estimation |
| Guardrails | 8002 | `/check` | Safety checks |
| Policy Engine | 8003 | `/decide` | Model selection |
| Prometheus | 9090 | `/metrics` | Metrics aggregation |
| Grafana | 3000 | `/` | Dashboards |

## Data Flow

```
Request → Controller (8084)
    │
    ├─→ Intent Classifier (8000) → ONNX or Heuristic
    ├─→ Complexity Estimator (8001) → ONNX or Heuristic
    ├─→ Guardrails (8002) → PII Detection
    └─→ Policy Engine (8003) → Model Selection
         │
         └─→ Backend (OpenRouter/OpenAI/Anthropic/etc.)
              │
              └─→ Response + Cost Tracking
```

## Key Components

### Controller (`controller/main.py`)
- **Purpose**: Main orchestrator and API gateway
- **Features**:
  - OpenAI-compatible API (`/v1/chat/completions`)
  - Prefix-based routing (`provider/model`)
  - Policy-based auto-routing (empty model + routing_policy)
  - Streaming support (SSE)
  - Retry logic with exponential backoff
  - Cost tracking per request
  - Prometheus metrics
  - Playground UI (`/playground`)

### Intent Classifier (`classifiers/intent/app.py`)
- **Purpose**: Classify user intent from prompt
- **Methods**:
  - ONNX model (DistilBERT) - if `INTENT_ONNX_PATH` set
  - Heuristic fallback (keyword matching)
- **Output**: `code_generation`, `reasoning`, `summarization`, `brainstorming`, `open_qa`, `chatbot`

### Complexity Estimator (`classifiers/complexity/app.py`)
- **Purpose**: Estimate prompt complexity
- **Methods**:
  - ONNX model (Logistic Regression) - if `COMPLEXITY_ONNX_PATH` set
  - Heuristic fallback (length-based)
- **Output**: `low`, `medium`, `high`

### Guardrails (`guardrails/app.py`)
- **Purpose**: Safety and compliance checks
- **Features**:
  - PII detection (SSN, email, phone, credit card, API keys)
  - Regex-based pattern matching
  - Masked logging for security
  - Prometheus metrics for blocked requests

### Policy Engine (`policy_engine/app.py`)
- **Purpose**: Make final routing decisions
- **Features**:
  - Maps intent → model selection
  - A/B testing support (configurable %)
  - Epsilon-greedy bandit (explore vs exploit)
  - Cost tier filtering
  - Returns chosen model + alternatives

### Cost Tracker (`controller/cost_tracker.py`)
- **Purpose**: Calculate and track LLM costs
- **Features**:
  - Model pricing database (OpenAI, Anthropic, OpenRouter)
  - Cost calculation from token usage
  - Per-model cost tracking
  - Metrics exported to Prometheus

## Configuration

### Main Config (`config.yaml`)
```yaml
backends:          # LLM provider configurations
  - name: openrouter
    prefix: openrouter/
    base_url: https://openrouter.ai/api/v1
    api_key_env: OPENROUTER_API_KEY

routing_rules:     # Fallback routing rules
  task_router:
    code_generation: openrouter/qwen/qwen3-coder:free
    chatbot: openrouter/google/gemma-3-27b-it:free

pipeline:          # Microservice URLs
  intent_classifier: http://intent:8000/classify
  complexity_estimator: http://complexity:8001/classify
  guardrails: http://guardrails:8002/check
  policy_engine: http://policy:8003/decide
```

### Environment Variables (`.env`)
```bash
# API Keys
OPENROUTER_API_KEY=sk-or-...
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...

# ONNX Model Paths
INTENT_ONNX_PATH=/app/intent_onnx/model.onnx
INTENT_TOKENIZER=distilbert-base-uncased
COMPLEXITY_ONNX_PATH=/app/complexity_onnx/model.onnx
```

## Observability

### Prometheus Metrics
- `orchestrator_requests_total` - Total requests
- `orchestrator_cost_total{provider, model}` - Cost tracking
- `orchestrator_tokens_total{type, provider, model}` - Token usage
- `intent_requests_total`, `complexity_requests_total`, etc.
- `guardrails_blocked_total{reason}` - PII detections

### Logging
- Structured JSON logging across all services
- Log levels: INFO, WARNING, ERROR
- Event tracking: `orchestrator_request`, `intent_classified`, etc.

### Grafana Dashboards
- Request rates and latency
- Cost breakdown by provider/model
- Token usage trends
- Error rates and PII detections

## Development Workflow

### Local Development
```bash
# Setup
make setup              # Create venv, install deps
make run                # Run controller locally

# Individual services
python classifiers/intent/app.py
python classifiers/complexity/app.py
python guardrails/app.py
python policy_engine/app.py
```

### Docker Development
```bash
# Start all services
make docker-up

# Check status
make docker-ps

# View logs
make docker-logs

# Stop
make docker-down

# Test
make docker-test
```

### Testing
```bash
# Run tests
make test

# Or directly
pytest tests/
```

## Deployment

### Docker Compose
All services orchestrated via `docker-compose.yml`:
- Services share default network
- Health checks configured
- Volumes for ONNX models
- Environment variables from `.env`

### Production Considerations
- Use production-ready configs (not mock backends)
- Set up proper API key management
- Configure Grafana data source persistence
- Set up Prometheus retention policies
- Configure log aggregation (optional)

## Future Enhancements

### Planned Features
- [ ] Redis caching layer
- [ ] Bandit persistence (Redis/Postgres)
- [ ] Multiple routing strategies (embedding-based, LLM-as-judge)
- [ ] Model catalog API
- [ ] Custom router training
- [ ] Rate limiting per user/API key
- [ ] Webhook support for routing events

### Documentation
- [ ] API reference documentation
- [ ] Deployment guide
- [ ] Performance tuning guide
- [ ] Custom model training guide
