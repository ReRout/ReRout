# Monitoring Setup for RouteLLM

## Quick Start

### 1. Access Grafana
- URL: http://localhost:3000
- Username: `admin`
- Password: `admin`

### 2. Configure Prometheus Data Source

1. Log in to Grafana
2. Click **Configuration** (gear icon) → **Data Sources**
3. Click **Add data source**
4. Select **Prometheus**
5. Configure:
   - **Name:** `Prometheus` (or any name)
   - **URL:** `http://prometheus:9090`
   - Click **Save & Test**
   - You should see: ✅ "Data source is working"

### 3. Import Dashboard

1. Go to **Dashboards** (grid icon) → **Import**
2. Click **Upload JSON file**
3. Select `monitoring/grafana-dashboard.json`
4. Or paste the JSON content directly
5. Select **Prometheus** as data source
6. Click **Import**

### 4. View Metrics

The dashboard will show:
- Total requests and errors
- Request latency (p50, p95)
- Intent classification rate
- Complexity classification rate
- Policy decision rate
- Request rates across all services

## Available Metrics

### Controller (Orchestrator)
- `orchestrator_requests_total` - Total requests
- `orchestrator_request_errors_total` - Total errors
- `orchestrator_request_latency_seconds` - Request latency histogram

### Intent Classifier
- `intent_requests_total` - Total classification requests
- `intent_request_errors_total` - Classification errors
- `intent_request_latency_seconds` - Classification latency

### Complexity Estimator
- `complexity_requests_total` - Total complexity requests
- `complexity_request_errors_total` - Complexity errors
- `complexity_request_latency_seconds` - Complexity latency

### Policy Engine
- `policy_requests_total` - Total policy decisions
- `policy_request_errors_total` - Policy errors
- `policy_request_latency_seconds` - Policy latency
- `policy_rewards_total{arm}` - Rewards per model (bandit)

### Guardrails
- Metrics available at `/metrics` endpoint

## Manual Prometheus Queries

Access Prometheus UI: http://localhost:9090

Try these queries:
```promql
# Request rate
rate(orchestrator_requests_total[5m])

# Error rate
rate(orchestrator_request_errors_total[5m])

# P95 latency
histogram_quantile(0.95, orchestrator_request_latency_seconds_bucket)

# Policy rewards by model
policy_rewards_total
```

## Troubleshooting

### Prometheus not scraping
1. Check Prometheus status: `docker compose ps prometheus`
2. Check Prometheus targets: http://localhost:9090/targets
3. Verify services are running: `docker compose ps`

### Grafana can't connect to Prometheus
1. Ensure both are on same network (default network in docker-compose)
2. Check Prometheus URL: `http://prometheus:9090` (service name, not localhost)
3. Verify Prometheus is accessible: `docker compose exec grafana wget -O- http://prometheus:9090/api/v1/status/config`

### No metrics showing
1. Generate some traffic to RouteLLM API
2. Check if metrics are being scraped: http://localhost:9090/targets
3. Verify metrics exist: http://localhost:9090/api/v1/label/__name__/values

