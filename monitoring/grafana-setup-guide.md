# Grafana Dashboard Setup Guide

## Quick Setup: Create Dashboard from Queries

### Step 1: Create New Dashboard
1. In Grafana, click **Dashboards** (grid icon, left sidebar)
2. Click **New** → **New Dashboard**
3. Click **Add visualization** (or **Add panel**)

### Step 2: Create Panels from Your Queries

For each query you've written, you need to create a panel:

#### Panel 1: Total Cost by Provider
1. In the query editor:
   - **Data source:** Prometheus
   - **Query:** `sum(orchestrator_cost_total) by (provider)`
   - Click **Run query** (you should see data)
2. Configure the visualization:
   - **Panel title:** "Total Cost by Provider"
   - **Visualization type:** Choose **Stat** or **Bar gauge** (from dropdown at top)
   - **Unit:** Currency → Dollar ($)
3. Click **Apply** (top right) to save the panel

#### Panel 2: Cost per Model
1. Click **Add panel** → **Add visualization**
2. Query: `sum(orchestrator_cost_total) by (model)`
3. Title: "Cost per Model"
4. Visualization: **Table** or **Bar chart**
5. Unit: Currency → Dollar ($)
6. Click **Apply**

#### Panel 3: Token Usage Rate
1. Click **Add panel** → **Add visualization**
2. Query: `sum(rate(orchestrator_tokens_total[5m])) by (type)`
3. Title: "Token Usage Rate (tokens/sec)"
4. Visualization: **Graph** or **Time series**
5. Unit: tokens/sec
6. Click **Apply**

#### Panel 4: Total Cost Over Time
1. Click **Add panel** → **Add visualization**
2. Query: `sum(rate(orchestrator_cost_total[1h]))`
3. Title: "Cost Rate (USD/hour)"
4. Visualization: **Graph**
5. Unit: Currency → Dollar ($)/hour
6. Click **Apply**

#### Panel 5: Request Rate
1. Click **Add panel** → **Add visualization**
2. Query: `rate(orchestrator_requests_total[5m])`
3. Title: "Request Rate (requests/sec)"
4. Visualization: **Graph**
5. Click **Apply**

#### Panel 6: Error Rate
1. Click **Add panel** → **Add visualization**
2. Query: `rate(orchestrator_request_errors_total[5m])`
3. Title: "Error Rate"
4. Visualization: **Graph**
5. Click **Apply**

#### Panel 7: P95 Latency
1. Click **Add panel** → **Add visualization**
2. Query: `histogram_quantile(0.95, orchestrator_request_latency_seconds_bucket)`
3. Title: "P95 Latency"
4. Visualization: **Graph**
5. Unit: seconds
6. Click **Apply**

### Step 3: Arrange Panels
- Drag panels to rearrange
- Resize panels by dragging corners
- Click panel title → **Edit** to modify

### Step 4: Save Dashboard
1. Click **Save dashboard** (top right, disc icon)
2. Name: "RouteLLM Metrics"
3. Click **Save**

### Step 5: View Dashboard
- Click **Dashboards** → Find your dashboard
- Click to view
- Dashboard auto-refreshes every 10s (configurable)

## Common Issues

### No Data Showing
1. **Generate some traffic first:**
   ```bash
   curl -X POST http://localhost:8084/v1/chat/completions \
     -H "Content-Type: application/json" \
     -d '{
       "model": "",
       "messages": [{"role": "user", "content": "Hello"}],
       "extra_body": {"routing_policy": "task_router"}
     }'
   ```

2. **Check Prometheus is scraping:**
   - Go to http://localhost:9090/targets
   - All targets should be "UP"

3. **Verify metrics exist:**
   - In Prometheus: http://localhost:9090/graph
   - Type `orchestrator_cost_total` and click Execute
   - Should show metrics

### Panel Shows "No Data"
- Check time range (top right) - try "Last 5 minutes"
- Verify query syntax is correct
- Check data source is "Prometheus"
- Make sure you've made requests to generate metrics

### Can't Find Dashboard
- Go to **Dashboards** → **Browse** → Find your dashboard name
- Or click **Home** (Grafana logo) → **Dashboards**

## Quick Reference: Panel Types

- **Stat**: Single number (good for totals, rates)
- **Graph/Time series**: Line chart (good for trends)
- **Bar gauge**: Horizontal bars (good for comparisons)
- **Table**: Tabular data (good for detailed breakdowns)
- **Pie chart**: Percentages (good for distribution)

