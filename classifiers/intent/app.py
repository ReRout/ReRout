from __future__ import annotations

import os
import time
import logging
from typing import Dict, Any, Optional, List

from fastapi import FastAPI
from pydantic import BaseModel
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from fastapi import Response

try:
    import onnxruntime as ort
except Exception:
    ort = None  # Optional

from transformers import AutoTokenizer
import numpy as np
from dotenv import load_dotenv

# Load .env so INTENT_ONNX_PATH etc. can be set persistently
load_dotenv()

app = FastAPI(title="RouteLLM - Intent Classifier", version="0.1.0")

# Logging (JSON)
logger = logging.getLogger("intent")
if not logger.handlers:
    from pythonjsonlogger import jsonlogger
    handler = logging.StreamHandler()
    formatter = jsonlogger.JsonFormatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

# Metrics
REQ_COUNTER = Counter("intent_requests_total", "Total intent requests")
REQ_ERRORS = Counter("intent_request_errors_total", "Intent request errors")
LATENCY = Histogram("intent_request_latency_seconds", "Intent request latency seconds")

# ONNX + Tokenizer
INTENT_ONNX_PATH = os.getenv("INTENT_ONNX_PATH")
INTENT_TOKENIZER = os.getenv("INTENT_TOKENIZER", "distilbert-base-uncased")
INTENT_MAX_LEN = int(os.getenv("INTENT_MAX_LEN", "256"))
INTENT_LABELS: List[str] = (os.getenv("INTENT_LABELS") or "code_generation,reasoning,summarization,brainstorming,open_qa,chatbot").split(",")
INTENT_LABELS = [l.strip() for l in INTENT_LABELS if l.strip()]

ORT_SESSION = None
TOKENIZER = None
if INTENT_ONNX_PATH and ort is not None and os.path.exists(INTENT_ONNX_PATH):
    try:
        ORT_SESSION = ort.InferenceSession(INTENT_ONNX_PATH, providers=["CPUExecutionProvider"])  # noqa: S603
        TOKENIZER = AutoTokenizer.from_pretrained(INTENT_TOKENIZER)
        logger.info({"event": "onnx_loaded", "path": INTENT_ONNX_PATH, "tokenizer": INTENT_TOKENIZER})
    except Exception as e:
        logger.error({"event": "onnx_load_failed", "error": str(e)})
        ORT_SESSION = None
        TOKENIZER = None


class ClassifyRequest(BaseModel):
    text: str
    context: Optional[Dict[str, Any]] = None


class ClassifyResponse(BaseModel):
    label: str
    confidence: float
    used: str


def classify_heuristic(text: str) -> ClassifyResponse:
    t = (text or "").lower()
    if "```" in t or "def " in t or "class " in t or "import " in t or "code" in t:
        return ClassifyResponse(label="code_generation", confidence=0.85, used="heuristic")
    if any(k in t for k in ["prove", "reason", "why", "explain step", "logic"]):
        return ClassifyResponse(label="reasoning", confidence=0.8, used="heuristic")
    if any(k in t for k in ["summarize", "tl;dr", "summary"]):
        return ClassifyResponse(label="summarization", confidence=0.8, used="heuristic")
    if any(k in t for k in ["brainstorm", "ideas", "story", "poem", "creative"]):
        return ClassifyResponse(label="brainstorming", confidence=0.75, used="heuristic")
    if any(k in t for k in ["qa", "question", "what is", "who is", "how to"]):
        return ClassifyResponse(label="open_qa", confidence=0.7, used="heuristic")
    return ClassifyResponse(label="chatbot", confidence=0.6, used="heuristic")


def softmax(x: np.ndarray) -> np.ndarray:
    x = x - np.max(x, axis=-1, keepdims=True)
    e = np.exp(x)
    return e / np.sum(e, axis=-1, keepdims=True)


def classify_onnx(text: str) -> Optional[ClassifyResponse]:
    if ORT_SESSION is None or TOKENIZER is None:
        return None
    inputs = TOKENIZER(
        text,
        return_tensors="np",
        truncation=True,
        max_length=INTENT_MAX_LEN,
        padding="max_length",
    )
    # Standard input names for HF exported models
    ort_inputs = {
        "input_ids": inputs["input_ids"].astype(np.int64),
        "attention_mask": inputs["attention_mask"].astype(np.int64),
    }
    if "token_type_ids" in inputs:
        ort_inputs["token_type_ids"] = inputs["token_type_ids"].astype(np.int64)

    outputs = ORT_SESSION.run(None, ort_inputs)
    logits = outputs[0]
    probs = softmax(logits)[0]
    idx = int(np.argmax(probs))
    label = INTENT_LABELS[idx % len(INTENT_LABELS)]
    conf = float(probs[idx]) if idx < len(probs) else 0.5
    return ClassifyResponse(label=label, confidence=conf, used="onnx")


@app.get("/metrics")
async def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/classify", response_model=ClassifyResponse)
async def classify(req: ClassifyRequest) -> ClassifyResponse:
    REQ_COUNTER.inc()
    start = time.perf_counter()
    try:
        res = classify_onnx(req.text) or classify_heuristic(req.text)
        logger.info({"event": "intent_classified", "label": res.label, "used": res.used})
        return res
    except Exception as e:
        REQ_ERRORS.inc()
        logger.exception({"event": "intent_error", "error": str(e)})
        raise
    finally:
        LATENCY.observe(time.perf_counter() - start)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
