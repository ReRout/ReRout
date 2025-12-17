from __future__ import annotations

import os
import time
import random
import logging
from typing import Dict, Any, List, Optional

from fastapi import FastAPI
from pydantic import BaseModel
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from fastapi import Response

app = FastAPI(title="RouteLLM - Policy Engine", version="0.1.0")

# Logging (JSON)
logger = logging.getLogger("policy")
if not logger.handlers:
    from pythonjsonlogger import jsonlogger
    handler = logging.StreamHandler()
    formatter = jsonlogger.JsonFormatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

# Metrics
REQ_COUNTER = Counter("policy_requests_total", "Total policy decide requests")
REQ_ERRORS = Counter("policy_request_errors_total", "Policy request errors")
LATENCY = Histogram("policy_request_latency_seconds", "Policy request latency seconds")
REWARD_COUNTER = Counter("policy_rewards_total", "Total rewards received", ["arm"])
COMPLEXITY_COUNTER = Counter("policy_complexity_total", "Requests by complexity level", ["complexity"]) 

# A/B and Bandit parameters
AB_ENABLED = os.getenv("AB_ENABLED", "false").lower() == "true"
AB_VARIANT_PCT = float(os.getenv("AB_VARIANT_PCT", "0.1"))  # 10%
BANDIT_EPSILON = float(os.getenv("BANDIT_EPSILON", "0.1"))  # 10% explore

# Label → Display mapping (friendly keys) - used as fallback for medium complexity
DEFAULT_MAP = {
    "code_generation": "qwen3-coder",
    "reasoning": "gpt-oss-20b",
    "summarization": "glm-4.5-air",
    "brainstorming": "llama-3.3-70b-instruct",
    "open_qa": "gpt-oss-20b",
    "chatbot": "gemma-3-27b-it",
}

# Display → provider/model mapping (OpenRouter free models only)
NAME_TO_MODEL = {
    "minimax-m2": "openrouter/minimax/minimax-m2:free",
    "glm-4.5-air": "openrouter/z-ai/glm-4.5-air:free",
    "qwen3-235b-a22b": "openrouter/qwen/qwen3-235b-a22b:free",
    "qwen3-coder": "openrouter/qwen/qwen3-coder:free",
    "llama-3.3-70b-instruct": "openrouter/meta-llama/llama-3.3-70b-instruct:free",
    "gpt-oss-20b": "openrouter/openai/gpt-oss-20b:free",
    "gemma-3-27b-it": "openrouter/google/gemma-3-27b-it:free",
}

DEFAULT_FALLBACK = "openrouter/minimax/minimax-m2:free"

# 2D Routing Matrix: (intent, complexity) → display model name
# This enables tiered model selection based on both task type AND difficulty
ROUTING_MATRIX: Dict[tuple, str] = {
    # Code generation: lightweight for simple, specialized coder for medium, largest for complex
    ("code_generation", "low"): "gemma-3-27b-it",
    ("code_generation", "medium"): "qwen3-coder",
    ("code_generation", "high"): "qwen3-235b-a22b",
    # Reasoning: lightweight for simple, reasoning-focused for medium/high
    ("reasoning", "low"): "gemma-3-27b-it",
    ("reasoning", "medium"): "gpt-oss-20b",
    ("reasoning", "high"): "qwen3-235b-a22b",
    # Summarization: lightweight for short texts, better models for longer
    ("summarization", "low"): "gemma-3-27b-it",
    ("summarization", "medium"): "glm-4.5-air",
    ("summarization", "high"): "llama-3.3-70b-instruct",
    # Brainstorming: lightweight for simple ideas, larger for creative tasks
    ("brainstorming", "low"): "gemma-3-27b-it",
    ("brainstorming", "medium"): "llama-3.3-70b-instruct",
    ("brainstorming", "high"): "qwen3-235b-a22b",
    # Open QA: lightweight for simple questions, better for complex
    ("open_qa", "low"): "gemma-3-27b-it",
    ("open_qa", "medium"): "gpt-oss-20b",
    ("open_qa", "high"): "llama-3.3-70b-instruct",
    # Chatbot: lightweight for casual, larger for complex conversations
    ("chatbot", "low"): "gemma-3-27b-it",
    ("chatbot", "medium"): "gemma-3-27b-it",
    ("chatbot", "high"): "llama-3.3-70b-instruct",
}

# Fallback by complexity when intent is unknown
COMPLEXITY_FALLBACK: Dict[str, str] = {
    "low": "gemma-3-27b-it",
    "medium": "gemma-3-27b-it",
    "high": "llama-3.3-70b-instruct",
}

# Cost tiers (static sample)
COST_TIERS: Dict[str, List[str]] = {
    "medium": [
        "openrouter/minimax/minimax-m2:free",
        "openrouter/z-ai/glm-4.5-air:free",
        "openrouter/qwen/qwen3-235b-a22b:free",
        "openrouter/qwen/qwen3-coder:free",
        "openrouter/meta-llama/llama-3.3-70b-instruct:free",
        "openrouter/openai/gpt-oss-20b:free",
        "openrouter/google/gemma-3-27b-it:free",
    ],
}

# In-memory bandit stats: successes/attempts per arm (model)
BANDIT_STATS: Dict[str, Dict[str, float]] = {}


class DecideRequest(BaseModel):
    labels: Dict[str, Any]
    user_tier: Optional[str] = None
    candidates: Optional[List[str]] = None
    constraints: Optional[Dict[str, Any]] = None


class DecideResponse(BaseModel):
    chosen: str
    alternatives: List[str]
    rationale: str
    ab_variant: Optional[str] = None


class RewardRequest(BaseModel):
    arm: str
    reward: float


def resolve_display_to_model(name: str) -> str:
    return NAME_TO_MODEL.get(name, DEFAULT_FALLBACK)


def choose_model(intent: str, complexity: str) -> str:
    """
    Choose model based on 2D routing matrix (intent x complexity).
    
    Fallback chain:
    1. Exact (intent, complexity) match in ROUTING_MATRIX
    2. Intent-only match in DEFAULT_MAP (medium complexity behavior)
    3. Complexity-only match in COMPLEXITY_FALLBACK
    4. Default fallback model
    """
    key = (intent, complexity)
    if key in ROUTING_MATRIX:
        display = ROUTING_MATRIX[key]
    elif intent in DEFAULT_MAP:
        # Fall back to intent-only (medium complexity behavior)
        display = DEFAULT_MAP[intent]
    elif complexity in COMPLEXITY_FALLBACK:
        # Fall back to complexity-only
        display = COMPLEXITY_FALLBACK[complexity]
    else:
        # Ultimate fallback
        display = "gemma-3-27b-it"
    return resolve_display_to_model(display)


def choose_primary(label: str) -> str:
    """Legacy function for backward compatibility - uses medium complexity."""
    return choose_model(label, "medium")


def ab_variant_choice(primary: str, alternatives: List[str]) -> Optional[str]:
    if not AB_ENABLED:
        return None
    if random.random() < AB_VARIANT_PCT and alternatives:
        return random.choice(alternatives)
    return None


def bandit_choose(primary: str, alternatives: List[str]) -> str:
    arms = [primary] + alternatives
    if random.random() < BANDIT_EPSILON:
        return random.choice(arms)
    # exploit: choose arm with best success rate
    def score(arm: str) -> float:
        stats = BANDIT_STATS.get(arm, {"success": 0.0, "trials": 0.0})
        s = stats["success"]
        t = stats["trials"]
        return (s / t) if t > 0 else 0.0
    arms.sort(key=score, reverse=True)
    return arms[0]


@app.get("/metrics")
async def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/decide", response_model=DecideResponse)
async def decide(req: DecideRequest) -> DecideResponse:
    REQ_COUNTER.inc()
    start = time.perf_counter()
    try:
        # Extract both intent AND complexity from labels
        intent = (req.labels or {}).get("intent", "chatbot")
        complexity = (req.labels or {}).get("complexity", "medium")
        
        # Track complexity distribution
        COMPLEXITY_COUNTER.labels(complexity=complexity).inc()
        
        # Use 2D routing matrix for model selection
        primary = choose_model(intent, complexity)
        
        # Alternatives are the rest of the cost tier set minus the primary
        all_candidates = COST_TIERS["medium"]
        alternatives: List[str] = [m for m in all_candidates if m != primary]

        variant = ab_variant_choice(primary, alternatives)
        chosen_pre_bandit = variant or primary
        chosen = bandit_choose(chosen_pre_bandit, [m for m in alternatives if m != chosen_pre_bandit])

        for arm in set([primary] + alternatives + [chosen]):
            if arm not in BANDIT_STATS:
                BANDIT_STATS[arm] = {"success": 0.0, "trials": 0.0}
        BANDIT_STATS[chosen]["trials"] += 1.0

        rationale = f"intent={intent} complexity={complexity} primary={primary} variant={variant} chosen={chosen}"
        logger.info({
            "event": "policy_decide",
            "intent": intent,
            "complexity": complexity,
            "primary": primary,
            "variant": variant,
            "chosen": chosen
        })
        return DecideResponse(chosen=chosen, alternatives=alternatives, rationale=rationale, ab_variant=variant)
    except Exception as e:
        REQ_ERRORS.inc()
        logger.exception({"event": "policy_error", "error": str(e)})
        raise
    finally:
        LATENCY.observe(time.perf_counter() - start)


@app.post("/reward")
async def reward(req: RewardRequest) -> Dict[str, Any]:
    arm = req.arm
    val = float(req.reward)
    REWARD_COUNTER.labels(arm=arm).inc()
    stats = BANDIT_STATS.setdefault(arm, {"success": 0.0, "trials": 0.0})
    stats["success"] += max(0.0, min(1.0, val))
    logger.info({"event": "policy_reward", "arm": arm, "reward": val, "success": stats["success"], "trials": stats["trials"]})
    return {"status": "ok", "arm": arm, "reward": val}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8003)
