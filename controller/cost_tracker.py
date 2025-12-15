from __future__ import annotations

from typing import Dict, Any, Optional

# Model pricing (per 1M tokens) - approximate pricing as of December 2025
# Format: "provider/model": {"input": price_per_1M_input_tokens, "output": price_per_1M_output_tokens}
MODEL_PRICING: Dict[str, Dict[str, float]] = {
    # OpenAI models
    "openai/gpt-5.2-pro": {"input": 21.00, "output": 168.00},  # Premium model for comparison
    "openai/gpt-5.2": {"input": 1.75, "output": 14.00},
    "openai/gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "openai/gpt-4o": {"input": 2.50, "output": 10.00},
    "openai/gpt-4": {"input": 30.00, "output": 60.00},
    "openai/gpt-3.5-turbo": {"input": 0.50, "output": 1.50},
    
    # Anthropic models (approximate)
    "anthropic/claude-sonnet-4-5-20250929": {"input": 3.00, "output": 15.00},
    "anthropic/claude-opus-4-1": {"input": 15.00, "output": 75.00},
    "anthropic/claude-3-haiku": {"input": 0.25, "output": 1.25},
    
    # OpenRouter free models
    "openrouter/minimax/minimax-m2:free": {"input": 0.0, "output": 0.0},
    "openrouter/z-ai/glm-4.5-air:free": {"input": 0.0, "output": 0.0},
    "openrouter/qwen/qwen3-235b-a22b:free": {"input": 0.0, "output": 0.0},
    "openrouter/qwen/qwen3-coder:free": {"input": 0.0, "output": 0.0},
    "openrouter/meta-llama/llama-3.3-70b-instruct:free": {"input": 0.0, "output": 0.0},
    "openrouter/openai/gpt-oss-20b:free": {"input": 0.0, "output": 0.0},
    "openrouter/google/gemma-3-27b-it:free": {"input": 0.0, "output": 0.0},
    
    # Mock models (for testing)
    "mock/gpt-4o-mini": {"input": 0.0, "output": 0.0},
    
    # Ollama (local, free)
    "ollama/llama3.3": {"input": 0.0, "output": 0.0},
    "ollama/qwen3": {"input": 0.0, "output": 0.0},
}

# Default pricing for unknown models (conservative estimate)
DEFAULT_PRICING = {"input": 1.00, "output": 3.00}


def get_model_pricing(provider_model: str) -> Dict[str, float]:
    """Get pricing for a model."""
    # Try exact match first
    if provider_model in MODEL_PRICING:
        return MODEL_PRICING[provider_model]
    
    # Try matching by provider/model pattern
    for model_key, pricing in MODEL_PRICING.items():
        if provider_model.startswith(model_key.split("/")[0] + "/"):
            # Use provider's default pricing for unknown models
            return DEFAULT_PRICING
    
    # Default for unknown models
    return DEFAULT_PRICING


def calculate_cost(
    provider_model: str,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
) -> Dict[str, Any]:
    """Calculate cost for a request."""
    pricing = get_model_pricing(provider_model)
    
    # Convert tokens to millions and multiply by price
    input_cost = (prompt_tokens / 1_000_000) * pricing["input"]
    output_cost = (completion_tokens / 1_000_000) * pricing["output"]
    total_cost = input_cost + output_cost
    
    return {
        "model": provider_model,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
        "input_cost": round(input_cost, 6),
        "output_cost": round(output_cost, 6),
        "total_cost": round(total_cost, 6),
        "input_price_per_1M": pricing["input"],
        "output_price_per_1M": pricing["output"],
    }


def estimate_cost_from_response(response: Dict[str, Any], provider_model: str) -> Dict[str, Any]:
    """Extract usage from response and calculate cost."""
    usage = response.get("usage", {})
    prompt_tokens = usage.get("prompt_tokens", 0)
    completion_tokens = usage.get("completion_tokens", 0)
    
    return calculate_cost(provider_model, prompt_tokens, completion_tokens)


# GPT-5.2 Pro pricing for comparison baseline
GPT_5_2_PRO_PRICING = {"input": 21.00, "output": 168.00}


def calculate_comparison_cost(
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
) -> Dict[str, Any]:
    """Calculate what GPT-5.2 Pro would have cost for the same tokens."""
    input_cost = (prompt_tokens / 1_000_000) * GPT_5_2_PRO_PRICING["input"]
    output_cost = (completion_tokens / 1_000_000) * GPT_5_2_PRO_PRICING["output"]
    total_cost = input_cost + output_cost
    
    return {
        "model": "openai/gpt-5.2-pro",
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
        "input_cost": round(input_cost, 6),
        "output_cost": round(output_cost, 6),
        "total_cost": round(total_cost, 6),
        "input_price_per_1M": GPT_5_2_PRO_PRICING["input"],
        "output_price_per_1M": GPT_5_2_PRO_PRICING["output"],
    }


def calculate_cost_with_comparison(
    provider_model: str,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
) -> Dict[str, Any]:
    """Calculate cost for a request with GPT-5.2 Pro comparison."""
    actual_cost = calculate_cost(provider_model, prompt_tokens, completion_tokens)
    comparison_cost = calculate_comparison_cost(prompt_tokens, completion_tokens)
    
    actual_total = actual_cost["total_cost"]
    comparison_total = comparison_cost["total_cost"]
    
    # Calculate savings
    if comparison_total > 0:
        savings_amount = comparison_total - actual_total
        savings_percentage = (savings_amount / comparison_total) * 100
    else:
        savings_amount = 0.0
        savings_percentage = 0.0
    
    return {
        **actual_cost,
        "comparison": {
            "model": "openai/gpt-5.2-pro",
            "total_cost": comparison_cost["total_cost"],
            "savings_amount": round(savings_amount, 6),
            "savings_percentage": round(savings_percentage, 2),
        }
    }

