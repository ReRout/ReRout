# Changelog

## [Unreleased] - Priority Features Implementation

### Added
- **Observability Stack**: Added Prometheus and Grafana to docker-compose
  - Prometheus scraping all microservices (controller, intent, complexity, guardrails, policy)
  - Grafana dashboard available at http://localhost:3000 (admin/admin)
  - Prometheus metrics at http://localhost:9090
  
- **Streaming Support**: Full streaming implementation for chat completions
  - SSE (Server-Sent Events) support
  - Streaming responses from backends
  - Mock streaming for testing
  - `routing_explain` included in first chunk of stream
  
- **Retry Logic**: Exponential backoff retry mechanism
  - 3 retry attempts with exponential backoff (1s, 2s, 4s, max 10s)
  - Retries on HTTP errors, network errors, and timeouts
  - Applied to both regular and streaming requests

### Fixed
- **Guardrails Healthcheck**: Fixed healthcheck to use POST request instead of GET
  - Guardrails service now shows as healthy in Docker

### Files Changed
- `docker-compose.yml`: Added Prometheus and Grafana services
- `monitoring/prometheus.yml`: Created Prometheus scrape configuration
- `controller/backends.py`: Added retry logic and streaming support
- `controller/main.py`: Added streaming response handling

### Usage

#### Streaming
```bash
curl -X POST http://localhost:8084/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "openrouter/qwen/qwen3-coder:free",
    "messages": [{"role": "user", "content": "Hello"}],
    "stream": true
  }'
```

#### Observability
- Prometheus: http://localhost:9090
- Grafana: http://localhost:3000 (admin/admin)
- Individual service metrics:
  - Controller: http://localhost:8084/metrics
  - Intent: http://localhost:8000/metrics
  - Complexity: http://localhost:8001/metrics
  - Guardrails: http://localhost:8002/metrics
  - Policy: http://localhost:8003/metrics

