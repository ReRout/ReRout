#!/bin/bash
# Test script for Sample API

API_URL="${API_URL:-http://localhost:9000}"

echo "🧪 Testing Sample API Wrapper"
echo "================================"
echo ""

echo "1. Health Check"
curl -s "$API_URL/health" | python3 -m json.tool || echo "❌ Failed"
echo ""

echo "2. Simple Chat Request"
curl -s -X POST "$API_URL/chat" \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [
      {"role": "user", "content": "Write Python code to parse JSON"}
    ],
    "use_auto_routing": true
  }' | python3 -m json.tool || echo "❌ Failed"
echo ""

echo "3. Chat with Auto-Routing"
curl -s -X POST "$API_URL/chat" \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [
      {"role": "user", "content": "Summarize this text: RouteLLM is a router..."}
    ],
    "use_auto_routing": true
  }' | python3 -m json.tool || echo "❌ Failed"
echo ""

echo "✅ Tests completed!"

