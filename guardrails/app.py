from __future__ import annotations

import re
import time
import logging
from typing import List, Dict, Any

from fastapi import FastAPI, Response
from pydantic import BaseModel
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST

app = FastAPI(title="RouteLLM - Guardrails", version="0.1.0")

# Logging (JSON)
logger = logging.getLogger("guardrails")
if not logger.handlers:
    from pythonjsonlogger import jsonlogger
    handler = logging.StreamHandler()
    formatter = jsonlogger.JsonFormatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

# Metrics
REQ_COUNTER = Counter("guardrails_requests_total", "Total guardrails check requests")
REQ_BLOCKED = Counter("guardrails_blocked_total", "Total blocked requests", ["reason"])
REQ_ERRORS = Counter("guardrails_request_errors_total", "Guardrails request errors")
LATENCY = Histogram("guardrails_request_latency_seconds", "Guardrails request latency seconds")

# Simple keyword blocklist (low-priority checks)
BLOCKLIST = ["api_key=", "password:", "secret="]

# PII Detection Patterns (regex)
PII_PATTERNS = {
    "ssn": [
        r"\b\d{3}-\d{2}-\d{4}\b",  # 123-45-6789
        r"\b\d{3}\s\d{2}\s\d{4}\b",  # 123 45 6789
        r"\b\d{9}\b",  # 123456789 (if suspicious context)
    ],
    "email": [
        r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
    ],
    "phone": [
        r"\b\d{3}-\d{3}-\d{4}\b",  # 123-456-7890
        r"\b\(\d{3}\)\s?\d{3}-\d{4}\b",  # (123) 456-7890
        r"\b\d{3}\.\d{3}\.\d{4}\b",  # 123.456.7890
        r"\b\+1\s?\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b",  # +1 123-456-7890
    ],
    "credit_card": [
        r"\b\d{4}[-.\s]?\d{4}[-.\s]?\d{4}[-.\s]?\d{4}\b",  # 1234-5678-9012-3456
        r"\b\d{13,19}\b",  # 13-19 digits (potential CC)
    ],
    "api_key": [
        r"\b(sk|pk|AKIA|ghp|gho)_[A-Za-z0-9]{20,}\b",  # Common API key prefixes
        r"\b[A-Za-z0-9]{32,}\b",  # Long alphanumeric strings
    ],
}


def detect_pii(text: str) -> List[Dict[str, Any]]:
    """Detect PII in text using regex patterns."""
    detections: List[Dict[str, Any]] = []
    text_lower = text.lower()
    
    # Check blocklist first (simple keyword matching)
    for keyword in BLOCKLIST:
        if keyword in text_lower:
            detections.append({"type": "blocklist", "pattern": keyword, "match": keyword})
    
    # Check PII patterns (regex)
    for pii_type, patterns in PII_PATTERNS.items():
        for pattern in patterns:
            matches = re.finditer(pattern, text, re.IGNORECASE)
            for match in matches:
                # Mask the actual value for logging
                matched_text = match.group(0)
                masked = matched_text[:4] + "*" * (len(matched_text) - 8) + matched_text[-4:] if len(matched_text) > 8 else "*" * len(matched_text)
                detections.append({
                    "type": pii_type,
                    "pattern": pattern,
                    "match": masked,
                    "position": match.start(),
                })
                # Only count first match per type per request
                break
    
    return detections


class GuardRequest(BaseModel):
    text: str
    strict: bool = False  # If True, block on any PII detection


class GuardResponse(BaseModel):
    passed: bool
    reasons: List[str]
    detections: List[Dict[str, Any]] = []


@app.get("/metrics")
async def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/check", response_model=GuardResponse)
async def check(req: GuardRequest) -> GuardResponse:
    REQ_COUNTER.inc()
    start = time.perf_counter()
    
    try:
        text = req.text or ""
        detections = detect_pii(text)
        reasons: List[str] = []
        
        if detections:
            # Group detections by type for cleaner reasons
            detection_types = {}
            for det in detections:
                pii_type = det["type"]
                if pii_type not in detection_types:
                    detection_types[pii_type] = []
                detection_types[pii_type].append(det.get("match", "detected"))
            
            # Build reasons list
            for pii_type, matches in detection_types.items():
                count = len(matches)
                reasons.append(f"PII detected: {pii_type} ({count} instance{'s' if count > 1 else ''})")
                REQ_BLOCKED.labels(reason=pii_type).inc()
        
        passed = len(reasons) == 0
        
        logger.info({
            "event": "guardrails_check",
            "passed": passed,
            "detection_count": len(detections),
            "detection_types": list(set(d["type"] for d in detections)),
        })
        
        return GuardResponse(
            passed=passed,
            reasons=reasons,
            detections=detections if req.strict else [],  # Only return detections in strict mode for security
        )
    except Exception as e:
        REQ_ERRORS.inc()
        logger.exception({"event": "guardrails_error", "error": str(e)})
        raise
    finally:
        LATENCY.observe(time.perf_counter() - start)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8002)
