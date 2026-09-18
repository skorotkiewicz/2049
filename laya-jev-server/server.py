"""HTTP API server for Laya, exposing the same "decisions" API as TypeSafe Jev.

Laya: https://github.com/NandhaKishorM/laya -- open-source (Apache 2.0),
self-hosted Jev-compatible decision model.

The model answers narrow, typed questions about a state. Your code owns the workflow.

Request (Jev-compatible):
    POST /v1/decisions
    {
      "model": "laya",                # optional, accepted for Jev compatibility
      "state": "Help! My payouts have been failing for 3 days.",  # str or dict
      "questions": {
        "is_urgent":   {"type": "noul",   "instructions": "..."},
        "department":  {"type": "choice", "instructions": "...", "criteria": {...}},
        "frustration": {"type": "score",  "instructions": "...", "criteria": [...]}
      }
    }

Response:
    {
      "model": "laya",
      "answers": {
        "is_urgent":   {"type": "noul",   "noul": 0.95},
        "department":  {"type": "choice", "choice": "billing", "probabilities": {...}, "confidence": 0.87},
        "frustration": {"type": "score",  "score": 1.05, "legend": {...}, "probabilities": {...}, "confidence": 0.71}
      },
      "usage": {"input_tokens": 128, "output_tokens": 0}
    }

Run:
    python server.py                       # http://0.0.0.0:8000
    LAYA_MODEL=/path/to/model python server.py
    uvicorn server:app --host 0.0.0.0 --port 8000

Requires: pip install fastapi uvicorn (plus laya, or the local model/ checkpoint).
"""

from __future__ import annotations

import json
import os
import threading
from typing import Any

try:
    from fastapi import FastAPI, HTTPException, Request
    from fastapi.responses import JSONResponse
    from pydantic import BaseModel, Field
except ImportError as exc:  # pragma: no cover
    raise SystemExit("server.py requires FastAPI: pip install fastapi uvicorn") from exc

# ---------------------------------------------------------------------------
# Model loading
# ---------------------------------------------------------------------------

LOCAL_MODEL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "model")
DEFAULT_HUB_MODEL = "convaiinnovations/laya"
VALID_QTYPES = ("choice", "score", "noul")


class LayaService:
    """Lazy-loading, thread-safe wrapper around the Laya decision model."""

    def __init__(self) -> None:
        self._agent: Any = None
        self._lock = threading.Lock()
        self._name = os.environ.get("LAYA_MODEL") or (LOCAL_MODEL_DIR if os.path.isdir(LOCAL_MODEL_DIR) else DEFAULT_HUB_MODEL)

    @property
    def name(self) -> str:
        return self._name if os.path.isdir(str(self._name)) else "laya"

    def _load(self) -> Any:
        if self._agent is not None:
            return self._agent
        with self._lock:
            if self._agent is None:  # double-checked: first request pays the load cost
                if os.path.isdir(self._name):
                    from rl_agent_api import RLAgent  # local checkpoint in ./model

                    self._agent = RLAgent(self._name)
                else:
                    import laya  # Hugging Face Hub checkpoint

                    self._agent = laya.load(self._name)
        return self._agent

    def predict(self, state: Any, questions: dict) -> dict:
        agent = self._load()
        predict = getattr(agent, "predict", None)
        if predict is not None:  # laya.Laya API
            result = predict(state, questions)
        else:  # RLAgent API (Jev request shape, Jev answer shape)
            result = agent.system_one(state, questions)
        result["model"] = self.name  # normalize: ignore whatever model name the backend reports
        return result


service = LayaService()

# ---------------------------------------------------------------------------
# Request / response validation
# ---------------------------------------------------------------------------


class QuestionDef(BaseModel):
    type: str = Field(description='One of "choice", "score", "noul"')
    instructions: str = Field(min_length=1)
    criteria: Any = Field(
        default=None,
        description="choice: {option: description} or [options]; score: ordered rubric list; noul: unused",
    )


class DecisionRequest(BaseModel):
    model: str | None = None  # accepted for Jev compatibility; served model is fixed at startup
    state: Any = Field(description="Text, email, ticket, or JSON document to ask questions about")
    questions: dict[str, QuestionDef] = Field(min_length=1)


def validate_questions(questions: dict[str, QuestionDef]) -> None:
    for qid, q in questions.items():
        if q.type not in VALID_QTYPES:
            raise HTTPException(
                status_code=422,
                detail={"error": f"question {qid!r}: type must be one of {list(VALID_QTYPES)}, got {q.type!r}"},
            )
        if q.type in ("choice", "score") and not q.criteria:
            raise HTTPException(
                status_code=422,
                detail={"error": f"question {qid!r}: type {q.type!r} requires 'criteria'"},
            )


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="Laya Decisions API", description="Jev-compatible typed decision API for Laya", version="1.0.0")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "model": service.name, "loaded": service._agent is not None}


@app.post("/v1/decisions")
@app.post("/decisions")  # Jev-style alias
async def decisions(req: DecisionRequest) -> JSONResponse:
    validate_questions(req.questions)

    questions = {qid: q.model_dump(exclude_none=False) for qid, q in req.questions.items()}
    try:
        result = await run_inference(req.state, questions)
    except ValueError as exc:  # e.g. options do not fit in head_max_len
        raise HTTPException(status_code=422, detail={"error": str(exc)}) from exc
    except Exception as exc:  # model / hardware failure
        raise HTTPException(status_code=500, detail={"error": f"inference failed: {exc}"}) from exc

    return JSONResponse(content=result)


_predict_lock = threading.Lock()  # the model is single-tenant; serialize concurrent calls


async def run_inference(state: Any, questions: dict) -> dict:
    """Run prediction off the event loop so slow inference never blocks the server."""
    import anyio

    def _predict() -> dict:
        with _predict_lock:
            return service.predict(state, questions)

    return await anyio.to_thread.run_sync(_predict)


if __name__ == "__main__":
    import uvicorn

    host = os.environ.get("LAYA_HOST", "0.0.0.0")
    port = int(os.environ.get("LAYA_PORT", "8000"))
    print(f"Serving Laya ({service.name}) on http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="info")
