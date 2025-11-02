# Quick Start Guide

## Prerequisites

1. **RouteLLM must be running** (either Docker or locally)
   ```bash
   # Option 1: Docker
   docker compose up -d
   
   # Option 2: Local
   python -m controller.main
   ```

2. **Python 3.9+ installed**

## Quick Start (3 steps)

### Step 1: Navigate to sample-api directory

```bash
# From project root
cd examples/sample-api
```

### Step 2: Install dependencies

```bash
# If using project venv (from root)
source ../../venv/bin/activate
pip install -r requirements.txt

# OR create new venv
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### Step 3: Run the API

```bash
# Set RouteLLM URL (if RouteLLM is in Docker, use localhost:8084)
export ROUTELLM_URL=http://localhost:8084

# Run
python3 app.py
```

The API will start on **http://localhost:9000**

## Test It

```bash
# In another terminal
curl -X POST http://localhost:9000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [
      {"role": "user", "content": "Write Python code to parse JSON"}
    ],
    "use_auto_routing": true
  }'
```

## Or Use the Helper Script

```bash
# From project root
cd examples/sample-api
./run.sh
```

The script will:
- Check if RouteLLM is running
- Install dependencies
- Start the API

## Troubleshooting

### "command not found: python"
Use `python3` instead:
```bash
python3 app.py
```

### "Cannot connect to RouteLLM"
Make sure RouteLLM is running:
```bash
# Check if RouteLLM is up
curl http://localhost:8084/health

# If not, start it
docker compose up -d  # From project root
```

### "Module not found"
Activate the virtual environment:
```bash
source ../../venv/bin/activate  # From sample-api directory
# OR
source venv/bin/activate  # If you created venv here
```

