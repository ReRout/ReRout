# Configuration and development reference

Run commands from the repository root.

## ⚙️ Configuration

### Basic Config (`config.yaml`)

```yaml
backends:
  - name: openrouter
    prefix: openrouter/
    base_url: https://openrouter.ai/api/v1
    api_key_env: OPENROUTER_API_KEY
    require_api_key: true

routing_rules:
  task_router:
    code_generation: openrouter/qwen/qwen3-coder:free
    chatbot: openrouter/google/gemma-3-27b-it:free

pipeline:
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

# ONNX Models (optional - falls back to heuristics)
# For Docker: use /app/intent_onnx/model.onnx
# For local: use absolute path to your model files
INTENT_ONNX_PATH=/app/intent_onnx/model.onnx
INTENT_TOKENIZER=distilbert-base-uncased
COMPLEXITY_ONNX_PATH=/app/complexity_onnx/model.onnx
```

### Memory Management

RouteLLM includes token-based conversation memory to maintain context across requests:

```yaml
memory:
  enabled: true  # Enable memory management
  max_tokens_per_conversation: 4000  # Max tokens per conversation
  max_total_tokens: 100000  # Max total tokens across all conversations
  pruning_strategy: "fifo"  # "fifo", "lifo", or "importance"
  storage_backend: "memory"  # "memory" (in-memory) or "redis" (persistent)
  redis_url: "redis://localhost:6379"  # Redis URL if using redis backend
```

**Usage in requests:**
```json
{
  "model": "",
  "messages": [{"role": "user", "content": "My name is Alice"}],
  "extra_body": {
    "routing_policy": "task_router",
    "use_memory": true,
    "user_id": "user123",
    "conversation_id": "conv-abc123"  // Optional: auto-generated if not provided
  }
}
```

See `examples/memory_usage.md` for detailed memory management documentation.

See `config.example.yaml` for full configuration options.

## 💡 Usage Examples

### 1. Prefix-Based Routing (Manual)

```bash
curl -X POST http://localhost:8084/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "openrouter/qwen/qwen3-coder:free",
    "messages": [{"role": "user", "content": "Write Python code"}]
  }'
```

### 2. Auto-Routing (Policy-Based)

```bash
curl -X POST http://localhost:8084/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "",
    "messages": [{"role": "user", "content": "Write Python code to parse JSON"}],
    "extra_body": {"routing_policy": "task_router"}
  }'
```

**Response includes `routing_explain`:**
```json
{
  "choices": [...],
  "routing_explain": {
    "source": "pipeline",
    "pipeline": {
      "intent": {"label": "code_generation", "confidence": 0.98},
      "complexity": {"level": "low", "confidence": 0.7},
      "guardrails": {"passed": true},
      "policy": {"chosen": "openrouter/qwen/qwen3-coder:free"}
    },
    "cost": {
      "total_cost_usd": 0.0,
      "prompt_tokens": 15,
      "completion_tokens": 200
    }
  }
}
```

### 3. Python Client

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8084/v1",
    api_key="dummy"  # Not required for local
)

# Auto-routing
response = client.chat.completions.create(
    model="",  # Empty for auto-route
    messages=[{"role": "user", "content": "Write Python code"}],
    extra_body={"routing_policy": "task_router"}
)

print(response.choices[0].message.content)
print(response.routing_explain)  # See routing decision
```

### 4. Streaming

```bash
curl -X POST http://localhost:8084/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "",
    "messages": [{"role": "user", "content": "Tell me a story"}],
    "stream": true,
    "extra_body": {"routing_policy": "task_router"}
  }'
```

## 💬 Chat UI

RouteLLM includes a production-ready chat interface built with [assistant-ui](https://github.com/assistant-ui/assistant-ui), providing a ChatGPT-like experience with automatic model routing.

### Features

- 🎨 **Modern UI** - Beautiful, customizable chat interface inspired by ChatGPT
- 🚀 **Streaming Support** - Real-time streaming responses
- 🧵 **Thread Management** - Multiple conversation threads with sidebar navigation
- 🎯 **Auto-Routing** - Automatically routes requests to optimal models based on intent
- ♿ **Accessible** - Built-in keyboard shortcuts and accessibility features
- 📝 **Markdown Support** - Rich markdown rendering with code highlighting

### Setup

1. **Navigate to the chat UI directory:**
   ```bash
   cd chat-ui
   ```

2. **Install dependencies:**
   ```bash
   npm install
   # or
   pnpm install
   # or
   yarn install
   ```

3. **Start the development server:**
   ```bash
   npm run dev
   # or
   pnpm dev
   # or
   yarn dev
   ```

4. **Open your browser:**
   Navigate to `http://localhost:4000` (or the port shown in your terminal)

### Configuration

The chat UI is pre-configured to connect to your RouteLLM backend at `http://localhost:8084`. The configuration is in `chat-ui/app/api/chat/route.ts`:

```typescript
model: openai("", {
  baseURL: "http://localhost:8084/v1",
  apiKey: "dummy", // Not required for local backend
}),
extraBody: {
  routing_policy: "task_router", // Auto-routing policy
}
```

### How It Works

1. **User sends a message** → Chat UI sends request to RouteLLM backend
2. **RouteLLM analyzes** → Intent classification, complexity estimation, guardrails
3. **Model selection** → Policy engine selects optimal model based on routing rules
4. **Response streaming** → Selected model generates response with real-time streaming
5. **Display** → Chat UI renders the response with markdown support

### Customization

The chat UI uses [assistant-ui](https://www.assistant-ui.com/), which provides composable primitives for complete customization:

- **Styling**: Modify components in `chat-ui/components/assistant-ui/`
- **Routing Policy**: Change `routing_policy` in `route.ts` to use different routing strategies
- **Backend URL**: Update `baseURL` if your RouteLLM backend runs on a different port
- **Model Selection**: Modify the model name or use specific models instead of auto-routing

### Requirements

- **RouteLLM Backend**: Must be running on `http://localhost:8084` (or update the `baseURL` in `route.ts`)
- **Node.js**: Version 18+ recommended
- **No API Keys Required**: The chat UI connects to your local backend, so no external API keys are needed

For more details, see the [chat-ui README](../chat-ui/README.md).

## 🐳 Docker Setup

### Quick Start

```bash
# Start all services
docker compose up -d

# Check status
docker compose ps

# View logs
docker compose logs -f

# Stop
docker compose down
```

### Services Included

- **Controller** - Main API (port 8084)
- **Intent Classifier** - ONNX/heuristic intent detection (port 8000)
- **Complexity Estimator** - ONNX/heuristic complexity detection (port 8001)
- **Guardrails** - PII detection (port 8002)
- **Policy Engine** - Model selection (port 8003)
- **Redis** - Memory storage backend (port 6379) - optional
- **Prometheus** - Metrics (port 9090)
- **Grafana** - Dashboards (port 3000)

### Makefile Commands

```bash
make docker-up      # Start all services
make docker-down    # Stop all services
make docker-ps      # Check status
make docker-logs     # View logs
make docker-test    # Run test requests
```

## 📊 Observability

### Prometheus Metrics

Access Prometheus at http://localhost:9090

**Key Metrics:**
- `orchestrator_requests_total` - Total API requests
- `orchestrator_cost_total{provider, model}` - Cost tracking
- `orchestrator_tokens_total{type, provider, model}` - Token usage
- `intent_requests_total` - Intent classification requests
- `guardrails_blocked_total{reason}` - PII detections

### Grafana Dashboards

Access Grafana at http://localhost:4000 (admin/admin)

**Setup:**
1. Configure Prometheus data source: `http://prometheus:9090`
2. Import dashboard from `monitoring/grafana-dashboard.json`
3. View real-time metrics and cost breakdowns

See `monitoring/README.md` for detailed setup instructions.

## 🛠️ Development

### Setup

```bash
# Install dependencies
make setup

# Run tests
make test

# Run locally (single process)
make run
```

### Project Structure

```
ReRout/
├── controller/          # Main orchestrator
├── classifiers/         # Intent & complexity services
├── guardrails/          # PII detection
├── policy_engine/       # Routing decisions
├── monitoring/          # Prometheus & Grafana configs
└── tests/              # Test suite
```

See `project structure.md` for detailed architecture.

### Running Individual Services

```bash
# Controller
python -m controller.main

# Intent Classifier
python classifiers/intent/app.py

# Complexity Estimator
python classifiers/complexity/app.py

# Guardrails
python guardrails/app.py

# Policy Engine
python policy_engine/app.py
```
