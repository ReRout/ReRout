#!/bin/bash
# Quick start script for Sample API

echo "🚀 Starting Sample API Wrapper"
echo "================================"
echo ""

# Check if RouteLLM is running
echo "Checking RouteLLM..."
if curl -s http://localhost:8084/health > /dev/null 2>&1; then
    echo "✅ RouteLLM is running"
else
    echo "❌ RouteLLM is not running on http://localhost:8084"
    echo "   Please start it first: docker compose up -d"
    exit 1
fi

# Set defaults
export ROUTELLM_URL=${ROUTELLM_URL:-http://localhost:8084}
export PORT=${PORT:-9000}

echo ""
echo "Configuration:"
echo "  RouteLLM URL: $ROUTELLM_URL"
echo "  Sample API Port: $PORT"
echo ""

# Check Python
if command -v python3 &> /dev/null; then
    PYTHON=python3
elif command -v python &> /dev/null; then
    PYTHON=python
else
    echo "❌ Python not found. Please install Python 3.9+"
    exit 1
fi

# Check if virtual environment exists
if [ -d "../../venv" ]; then
    echo "Activating virtual environment..."
    source ../../venv/bin/activate
else
    echo "Creating virtual environment..."
    $PYTHON -m venv ../../venv
    source ../../venv/bin/activate
fi

# Install dependencies
echo ""
echo "Installing dependencies..."
pip install -q -r requirements.txt

echo ""
echo "Starting Sample API on http://localhost:$PORT"
echo "Press Ctrl+C to stop"
echo ""
echo "Test it: curl -X POST http://localhost:$PORT/chat \\"
echo "  -H 'Content-Type: application/json' \\"
echo "  -d '{\"messages\": [{\"role\": \"user\", \"content\": \"Hello!\"}]}'"
echo ""

$PYTHON app.py

