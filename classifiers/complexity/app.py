from __future__ import annotations

import os
import time
import logging
from fastapi import FastAPI
from pydantic import BaseModel
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from fastapi import Response

try:
    import onnxruntime as ort
except Exception:
    ort = None  # Optional

from dotenv import load_dotenv  # NEW
import numpy as np  # NEW

# Load .env so COMPLEXITY_ONNX_PATH can be set persistently
load_dotenv()

app = FastAPI(title="RouteLLM - Complexity Estimator", version="0.1.0")

# Logging (JSON)
logger = logging.getLogger("complexity")
if not logger.handlers:
    from pythonjsonlogger import jsonlogger
    handler = logging.StreamHandler()
    formatter = jsonlogger.JsonFormatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

# Metrics
REQ_COUNTER = Counter("complexity_requests_total", "Total complexity requests")
REQ_ERRORS = Counter("complexity_request_errors_total", "Complexity request errors")
LATENCY = Histogram("complexity_request_latency_seconds", "Complexity request latency seconds")

# Optional ONNX session
COMPLEXITY_ONNX_PATH = os.getenv("COMPLEXITY_ONNX_PATH")
ORT_SESSION = None
if COMPLEXITY_ONNX_PATH and ort is not None and os.path.exists(COMPLEXITY_ONNX_PATH):
    try:
        ORT_SESSION = ort.InferenceSession(COMPLEXITY_ONNX_PATH, providers=["CPUExecutionProvider"])  # noqa: S603
        logger.info({"event": "onnx_loaded", "path": COMPLEXITY_ONNX_PATH})
    except Exception as e:
        logger.error({"event": "onnx_load_failed", "error": str(e)})
        ORT_SESSION = None


class ComplexityRequest(BaseModel):
    text: str


class ComplexityResponse(BaseModel):
    level: str
    confidence: float
    used: str


def classify_heuristic(text: str) -> ComplexityResponse:
    """Heuristic complexity classification based on text length and structure."""
    length = len(text or "")
    
    # Count sentences, questions, code blocks, etc. for better heuristics
    sentence_count = (text or "").count(".") + (text or "").count("!") + (text or "").count("?")
    has_code = "```" in (text or "") or "def " in (text or "") or "class " in (text or "")
    has_questions = "?" in (text or "") or "how" in (text or "").lower() or "why" in (text or "").lower()
    
    # More nuanced classification
    if length < 100:
        level = "low"
        confidence = 0.8
    elif length < 300:
        # Medium length: check for complexity indicators
        if has_code or sentence_count > 3:
            level = "medium"
            confidence = 0.75
        else:
            level = "low"
            confidence = 0.7
    elif length < 800:
        level = "medium"
        confidence = 0.75
    else:
        level = "high"
        confidence = 0.8
    
    # Boost complexity for code or structured content
    if has_code and length > 200:
        level = "high"
        confidence = 0.85
    
    return ComplexityResponse(level=level, confidence=confidence, used="heuristic")


def classify_onnx(text: str) -> ComplexityResponse | None:
    if ORT_SESSION is None:
        return None
    # Build 1D normalized length feature the ONNX model expects
    text_len = len(text or "")
    norm_len = min(text_len, 1200) / 1200.0
    feature = np.array([[norm_len]], dtype=np.float32)
    # Input name must match the exported graph; using 'input' per export snippet
    try:
        outputs = ORT_SESSION.run(None, {"input": feature})
        
        # Handle different ONNX model output formats
        # Format 1: Two outputs [output_label, output_probability]
        # Format 2: Single output with logits/probabilities
        if len(outputs) == 2:
            # Model has separate label and probability outputs
            output_label = outputs[0]
            output_probability = outputs[1]
            
            # Extract class index (handle different shapes)
            if isinstance(output_label, np.ndarray):
                if output_label.ndim == 0:
                    idx = int(output_label)
                elif output_label.ndim == 1:
                    idx = int(output_label[0])
                else:
                    idx = int(output_label.flat[0])
            else:
                # Fallback for other types
                idx = int(output_label[0]) if hasattr(output_label, '__getitem__') else int(output_label)
            
            # Extract confidence from probability output
            # output_probability can be: numpy array, list of dicts, or dict
            confidence = 0.7  # Default
            try:
                if isinstance(output_probability, dict):
                    # Direct dict: {0: prob0, 1: prob1, 2: prob2}
                    confidence = float(output_probability.get(idx, 0.7))
                elif isinstance(output_probability, list) and len(output_probability) > 0:
                    # List of dicts: [{0: prob0, 1: prob1, 2: prob2}]
                    if isinstance(output_probability[0], dict):
                        confidence = float(output_probability[0].get(idx, 0.7))
                    elif isinstance(output_probability[0], (list, np.ndarray)):
                        # List/array of probabilities
                        if idx < len(output_probability[0]):
                            confidence = float(output_probability[0][idx])
                    else:
                        # Try to access directly if it's a list of numbers
                        if idx < len(output_probability):
                            confidence = float(output_probability[idx])
                elif isinstance(output_probability, np.ndarray):
                    if output_probability.ndim == 1 and idx < len(output_probability):
                        confidence = float(output_probability[idx])
                    elif output_probability.ndim == 2 and output_probability.shape[0] > 0 and idx < output_probability.shape[1]:
                        confidence = float(output_probability[0][idx])
            except (KeyError, IndexError, TypeError, AttributeError) as e:
                logger.debug({"event": "confidence_extraction_failed", "error": str(e), "idx": idx})
                confidence = 0.7
        else:
            # Single output (logits or probabilities)
            logits = outputs[0]
            if logits.ndim == 1:
                # Single-element array with class index
                if logits.shape[0] == 1:
                    # Direct class index
                    idx = int(logits[0])
                    confidence = 0.7
                else:
                    # Probability distribution
                    idx = int(np.argmax(logits))
                    # Normalize to get confidence
                    if len(logits) > 1:
                        exp_probs = np.exp(logits - np.max(logits))
                        softmax_probs = exp_probs / np.sum(exp_probs)
                        confidence = float(softmax_probs[idx])
                    else:
                        confidence = 0.7
            else:
                # 2D output
                idx = int(np.argmax(logits, axis=1)[0])
                if logits.shape[1] > idx:
                    exp_probs = np.exp(logits[0] - np.max(logits[0]))
                    softmax_probs = exp_probs / np.sum(exp_probs)
                    confidence = float(softmax_probs[idx])
                else:
                    confidence = 0.7
        
        mapping = {0: "low", 1: "medium", 2: "high"}
        level = mapping.get(idx, "medium")
        
        # Log for debugging
        try:
            outputs_shape = [o.shape if hasattr(o, 'shape') else type(o).__name__ for o in outputs]
            outputs_repr = []
            for o in outputs:
                if hasattr(o, 'tolist'):
                    outputs_repr.append(o.tolist())
                elif isinstance(o, (list, dict)):
                    outputs_repr.append(o)
                else:
                    outputs_repr.append(str(o))
            logger.debug({
                "event": "onnx_classification",
                "text_len": text_len,
                "norm_len": norm_len,
                "outputs_shape": outputs_shape,
                "outputs": outputs_repr,
                "idx": idx,
                "level": level,
                "confidence": confidence
            })
        except Exception as log_err:
            logger.debug({"event": "onnx_classification_log_failed", "error": str(log_err)})
        
        return ComplexityResponse(level=level, confidence=confidence, used="onnx")
    except Exception as e:
        logger.error({"event": "onnx_infer_failed", "error": str(e), "text_len": text_len})
        return None


@app.get("/metrics")
async def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/classify", response_model=ComplexityResponse)
async def classify(req: ComplexityRequest) -> ComplexityResponse:
    REQ_COUNTER.inc()
    start = time.perf_counter()
    try:
        # Try ONNX first, but fall back to heuristic if:
        # 1. ONNX fails, OR
        # 2. ONNX always returns "low" and text is clearly longer/more complex
        onnx_result = classify_onnx(req.text)
        if onnx_result:
            text_len = len(req.text or "")
            # If ONNX says "low" but text is clearly medium/high complexity, use heuristic
            if onnx_result.level == "low" and text_len > 300:
                heuristic_result = classify_heuristic(req.text)
                # Only use heuristic if it suggests higher complexity
                if heuristic_result.level != "low":
                    logger.info({
                        "event": "complexity_fallback_to_heuristic",
                        "onnx_level": onnx_result.level,
                        "heuristic_level": heuristic_result.level,
                        "text_len": text_len,
                        "reason": "onnx_always_low_despite_complex_text"
                    })
                    res = heuristic_result
                else:
                    res = onnx_result
            else:
                res = onnx_result
        else:
            # ONNX not available, use heuristic
            res = classify_heuristic(req.text)
        
        logger.info({"event": "complexity_classified", "level": res.level, "used": res.used, "text_len": len(req.text or "")})
        return res
    except Exception as e:
        REQ_ERRORS.inc()
        logger.exception({"event": "complexity_error", "error": str(e)})
        raise
    finally:
        LATENCY.observe(time.perf_counter() - start)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8001)
