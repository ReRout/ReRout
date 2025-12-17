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

from dotenv import load_dotenv
import numpy as np
import re
from typing import Dict

# Load .env so COMPLEXITY_ONNX_PATH can be set persistently
load_dotenv()

# Technical terms that indicate complexity (domain vocabulary)
TECHNICAL_TERMS = {
    # Programming
    "algorithm", "recursion", "async", "await", "callback", "closure", "decorator",
    "inheritance", "polymorphism", "encapsulation", "abstraction", "interface",
    "microservice", "api", "database", "sql", "nosql", "graphql", "rest",
    "kubernetes", "docker", "ci/cd", "devops", "terraform", "aws", "gcp", "azure",
    # Math/Science
    "derivative", "integral", "matrix", "vector", "eigenvalue", "probability",
    "statistics", "regression", "optimization", "gradient", "tensor", "neural",
    "quantum", "entropy", "thermodynamics", "kinetics",
    # Business/Technical
    "architecture", "scalability", "latency", "throughput", "distributed",
    "consensus", "replication", "sharding", "caching", "indexing",
}

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


def extract_features(text: str) -> Dict[str, float]:
    """
    Extract semantic features from text for complexity classification.
    
    Features:
    - length_score: Normalized text length (0-1)
    - question_depth: Analytical complexity based on question patterns
    - has_code: Code patterns detected (0 or 1)
    - has_math: Mathematical notation detected (0 or 1)
    - nested_requirements: Multi-step task indicators
    - technical_density: Ratio of technical terms in text
    """
    t = text or ""
    t_lower = t.lower()
    length = len(t)
    words = t_lower.split()
    word_count = max(len(words), 1)
    
    # Length score: normalized to 0-1, caps at 500 chars
    length_score = min(length / 500.0, 1.0)
    
    # Question depth: analytical terms that suggest complex reasoning
    analytical_patterns = [
        r'\bexplain\b', r'\banalyze\b', r'\bcompare\b', r'\bcontrast\b',
        r'\bevaluate\b', r'\bprove\b', r'\bderive\b', r'\bjustify\b',
        r'\bcritique\b', r'\bsynthesiz', r'\bimplement\b', r'\bdesign\b',
        r'\boptimize\b', r'\bdebug\b', r'\brefactor\b', r'\barchitect\b',
    ]
    question_count = t.count("?")
    analytical_matches = sum(1 for p in analytical_patterns if re.search(p, t_lower))
    question_depth = min((question_count + analytical_matches * 2) / 5.0, 1.0)
    
    # Code detection: broader pattern matching
    code_patterns = [
        r'```',                              # Code blocks
        r'\bdef\s+\w+\s*\(',                 # Python functions
        r'\bclass\s+\w+',                    # Class definitions
        r'\bfunction\s+\w+\s*\(',            # JS functions
        r'\bconst\s+\w+\s*=',                # JS const
        r'\blet\s+\w+\s*=',                  # JS let
        r'\bvar\s+\w+\s*=',                  # JS var
        r'\bimport\s+[\w{]',                 # Import statements
        r'\bfrom\s+\w+\s+import\b',          # Python imports
        r'\breturn\s+',                      # Return statements
        r'=>',                               # Arrow functions
        r'\bif\s*\(.+\)\s*{',                # If statements with braces
        r'\bfor\s*\(.+\)\s*{',               # For loops
        r'\bwhile\s*\(.+\)',                 # While loops
        r'SELECT\s+.+\s+FROM',               # SQL
        r'CREATE\s+TABLE',                   # SQL DDL
    ]
    has_code = 1.0 if any(re.search(p, t, re.IGNORECASE) for p in code_patterns) else 0.0
    
    # Math detection: formulas and mathematical notation
    math_patterns = [
        r'[∫∑∏√∞≤≥≠±×÷∈∉∅∀∃∧∨¬⊂⊃∪∩]',       # Math symbols
        r'\\frac\{',                         # LaTeX fractions
        r'\\int\b',                          # LaTeX integrals
        r'\\sum\b',                          # LaTeX sums
        r'\\sqrt\{',                         # LaTeX square root
        r'\bequation\b',                     # Equation mention
        r'\bformula\b',                      # Formula mention
        r'\bderivative\b',                   # Calculus
        r'\bintegral\b',                     # Calculus
        r'\bmatrix\b',                       # Linear algebra
        r'\bvector\b',                       # Linear algebra
        r'\beigenvalue\b',                   # Linear algebra
        r'\bprobability\b',                  # Statistics
        r'\^{?\d+}?',                        # Exponents like x^2 or x^{2}
        r'_\{?\d+\}?',                       # Subscripts
        r'\d+\s*[+\-*/]\s*\d+\s*=',          # Arithmetic equations
    ]
    has_math = 1.0 if any(re.search(p, t) for p in math_patterns) else 0.0
    
    # Nested requirements: conjunctions indicating multi-step tasks
    nested_patterns = [
        r'\band\s+then\b',
        r'\bfirst\b.*\bthen\b',
        r'\bstep\s*\d',
        r'\b(?:also|additionally|furthermore|moreover)\b',
        r'\bbefore\b.*\bafter\b',
        r'\brequir(?:e|es|ing)\b.*\band\b',
    ]
    conjunction_count = t_lower.count(" and ") + t_lower.count(" or ") + t_lower.count(", then ")
    nested_pattern_matches = sum(1 for p in nested_patterns if re.search(p, t_lower))
    nested_requirements = min((conjunction_count + nested_pattern_matches * 2) / 6.0, 1.0)
    
    # Technical term density
    technical_count = sum(1 for word in words if word.strip(".,!?;:()[]{}") in TECHNICAL_TERMS)
    technical_density = min(technical_count / max(word_count, 1) * 10, 1.0)  # Scale up for visibility
    
    return {
        "length_score": length_score,
        "question_depth": question_depth,
        "has_code": has_code,
        "has_math": has_math,
        "nested_requirements": nested_requirements,
        "technical_density": technical_density,
    }


def classify_heuristic(text: str) -> ComplexityResponse:
    """
    Semantic complexity classification using weighted feature scoring.
    
    This replaces the pure length-based heuristic with a multi-dimensional
    analysis of text complexity including code patterns, math notation,
    analytical language, and technical vocabulary.
    """
    features = extract_features(text)
    
    # Weighted scoring formula
    # Weights sum to 1.0 for interpretability
    score = (
        features["length_score"] * 0.20 +           # Text length (reduced weight)
        features["question_depth"] * 0.25 +         # Analytical complexity
        features["has_code"] * 0.20 +               # Code presence
        features["has_math"] * 0.15 +               # Math presence
        features["nested_requirements"] * 0.10 +    # Multi-step tasks
        features["technical_density"] * 0.10        # Technical vocabulary
    )
    
    # Classify based on score thresholds
    if score < 0.25:
        level = "low"
        # Confidence is higher when score is clearly in the low range
        confidence = 0.7 + (0.25 - score) * 0.4  # 0.7-0.8
    elif score < 0.55:
        level = "medium"
        # Confidence peaks in middle of medium range
        distance_from_center = abs(score - 0.4)
        confidence = 0.75 - distance_from_center * 0.3  # ~0.65-0.75
    else:
        level = "high"
        # Confidence increases with score for high complexity
        confidence = 0.7 + min(score - 0.55, 0.2) * 0.5  # 0.7-0.8
    
    # Clamp confidence
    confidence = max(0.5, min(0.9, confidence))
    
    # Log features for debugging
    logger.debug({
        "event": "complexity_features",
        "features": features,
        "score": round(score, 3),
        "level": level,
        "confidence": round(confidence, 3)
    })
    
    return ComplexityResponse(level=level, confidence=round(confidence, 2), used="heuristic")


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
