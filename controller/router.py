from __future__ import annotations

from typing import Dict, Tuple, Optional, List

from .config import Config


def resolve_alias(model: str, config: Config) -> str:
    return config.aliases.get(model, model)


def parse_model(model: str) -> Tuple[str, str]:
    if "/" not in model:
        raise ValueError("Model must be in 'provider/model' format")
    provider, model_name = model.split("/", 1)
    if not provider or not model_name:
        raise ValueError("Invalid model format; expected 'provider/model'")
    return provider, model_name


def _last_user_message(messages: List[Dict[str, str]]) -> str:
    for m in reversed(messages):
        if m.get("role") == "user":
            return m.get("content", "")
    return messages[-1].get("content", "") if messages else ""


def classify_heuristic(messages: List[Dict[str, str]]) -> str:
    text = (_last_user_message(messages) or "").lower()
    if "```" in text or "def " in text or "class " in text or "import " in text or "code" in text:
        return "code_generation"
    if any(k in text for k in ["prove", "reason", "why", "explain step", "chain of thought", "logic"]):
        return "reasoning"
    if any(k in text for k in ["summarize", "tl;dr", "summary"]):
        return "summarization"
    if any(k in text for k in ["brainstorm", "ideas", "story", "poem", "creative"]):
        return "brainstorming"
    if any(k in text for k in ["qa", "question", "what is", "who is", "how to"]):
        return "open_qa"
    return "chatbot"


def choose_model_for_policy(messages: List[Dict[str, str]], config: Config, policy_name: Optional[str]) -> Optional[str]:
    if not policy_name:
        return None

    classification = classify_heuristic(messages)

    # Look for routing_rules.<policy_name>.<classification>
    rules = (config.raw or {}).get("routing_rules", {})
    policy_rules = rules.get(policy_name, {}) if isinstance(rules, dict) else {}
    model = policy_rules.get(classification)
    if model:
        return model

    # Fallback: try alias map for common labels
    alias_fallbacks = {
        "code_generation": config.aliases.get("code"),
        "reasoning": config.aliases.get("reason"),
        "summarization": config.aliases.get("gpt4mini"),
        "brainstorming": config.aliases.get("opus") or config.aliases.get("sonnet"),
        "open_qa": config.aliases.get("gpt4"),
        "chatbot": config.aliases.get("local") or config.aliases.get("gpt4mini"),
    }
    model = alias_fallbacks.get(classification)
    if model:
        return model

    # Last resort: pick first backend default model name unknown → caller will split
    default_backend = next((b for b in config.backends if b.get("default")), None)
    if default_backend:
        return f"{default_backend.get('name')}/gpt-4o-mini"

    if config.backends:
        first = config.backends[0]
        return f"{first.get('name')}/gpt-4o-mini"

    return None
