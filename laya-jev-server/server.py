"""HTTP API server for Laya, exposing the same "decisions" API as TypeSafe Jev.

Laya: https://github.com/NandhaKishorM/laya -- open-source (Apache 2.0),
self-hosted Jev-compatible decision model.

For Laya: v0.3.3

The model answers narrow, typed questions about a state. Your code owns the workflow.
Requests are served by `laya.Router`, which picks the right checkpoint per request:

    english          convaiinnovations/laya                  421M, 512 tokens, English
    multilingual     convaiinnovations/laya-multilingual     322M, 1024 tokens, 100+ languages
    typed-decisions  convaiinnovations/laya-typed-decisions  421M, 1024 tokens, fine-tuned

Request (Jev-compatible):
    POST /v1/decisions
    {
      "model": "laya",                # optional; checkpoint hint ("english", "multilingual",
                                      # "typed-decisions" or a repo id) for Jev compatibility
      "lang": "en",                   # optional; pin the language instead of auto-detecting
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
      "routing": {"model": "english", "repo": "convaiinnovations/laya", "reason": "English Latin text"},
      "usage": {"input_tokens": 128, "output_tokens": 0}
    }

Run:
    python server.py                       # http://0.0.0.0:8000
    LAYA_PRELOAD=1 LAYA_DEVICE=cuda python server.py
    uvicorn server:app --host 0.0.0.0 --port 8000

Environment:
    LAYA_MODEL      hub repo id (default "convaiinnovations/laya") or path to a local checkpoint
    LAYA_DEVICE     "cpu", "cuda", ... (default: let torch decide)
    LAYA_PRELOAD    "1" to build every checkpoint at startup so routing is free (default: lazy)
    LAYA_MAX_LOADED how many checkpoints stay resident (default 1, LRU eviction)
    LAYA_DEFAULT    default checkpoint when routing is ambiguous (default "english")

Requires: pip install fastapi uvicorn (plus laya, or the local model/ checkpoint).
"""

from __future__ import annotations

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


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


class LayaService:
    """Lazy-loading, thread-safe wrapper around the Laya decision model.

    Uses `laya.Router` (README: "Three checkpoints, and a `Router` that picks between
    them per request"). If a local checkpoint exists in ./model it is attached to the
    router as the "english" checkpoint instead of a duplicate download.
    """

    def __init__(self) -> None:
        self._router: Any = None
        self._lock = threading.Lock()
        self._name = os.environ.get("LAYA_MODEL") or (LOCAL_MODEL_DIR if os.path.isdir(LOCAL_MODEL_DIR) else DEFAULT_HUB_MODEL)

    @property
    def name(self) -> str:
        return self._name if os.path.isdir(str(self._name)) else "laya"

    @property
    def router(self) -> Any:
        router = self._router
        if router is not None:
            return router
        with self._lock:
            if self._router is None:  # double-checked: first request pays the load cost
                import laya

                router = laya.Router(
                    device=os.environ.get("LAYA_DEVICE") or None,
                    max_loaded=int(os.environ.get("LAYA_MAX_LOADED", "1")),
                    default=os.environ.get("LAYA_DEFAULT", "english"),
                    preload=_env_flag("LAYA_PRELOAD"),
                )
                if os.path.isdir(self._name):
                    # local checkpoint: hand it to the router rather than download a copy
                    from rl_agent_api import RLAgent  # type: ignore  # legacy local runtime

                    try:
                        router.attach("english", laya.load(self._name))
                    except AttributeError:  # very old laya builds without laya.load
                        router.attach("english", RLAgent(self._name))
                self._router = router
            return self._router

    def route(self, state: Any, questions: dict, model: str | None = None, lang: str | None = None) -> Any:
        """Decide which checkpoint serves this request, without loading or running anything."""
        return self.router.route(state, questions, model=model or None, lang=lang or None)

    def predict(self, state: Any, questions: dict, model: str | None = None, lang: str | None = None) -> dict:
        result = self.router.predict(state, questions, model=model or None, lang=lang or None)
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
    model: str | None = Field(
        default=None,
        description='Optional checkpoint hint: "english", "multilingual", "typed-decisions" or a repo id',
    )
    lang: str | None = Field(
        default=None,
        description="Optional language code (e.g. \"en\", \"de\"); overrides automatic script detection",
    )
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
    router = service._router
    return {
        "status": "ok",
        "model": service.name,
        "loaded": router is not None,
        "checkpoints_loaded": router.loaded if router is not None else [],
        "max_loaded": int(os.environ.get("LAYA_MAX_LOADED", "1")),
    }


@app.get("/route")
def route(state: Any = None, questions: dict | None = None, model: str | None = None, lang: str | None = None) -> dict:
    """Inspect the routing decision for a request without running the model."""
    try:
        decision = service.route(state or {}, questions or {}, model=model, lang=lang)
    except KeyError as exc:  # unknown checkpoint name
        raise HTTPException(status_code=422, detail={"error": str(exc)}) from exc
    return dict(decision)


@app.post("/v1/decisions")
@app.post("/decisions")  # Jev-style alias
async def decisions(req: DecisionRequest) -> JSONResponse:
    validate_questions(req.questions)

    questions = {qid: q.model_dump(exclude_none=False) for qid, q in req.questions.items()}
    try:
        result = await run_inference(req.state, questions, model=req.model, lang=req.lang)
    except ValueError as exc:  # e.g. options do not fit in head_max_len
        raise HTTPException(status_code=422, detail={"error": str(exc)}) from exc
    except KeyError as exc:  # unknown checkpoint name / language
        raise HTTPException(status_code=422, detail={"error": str(exc)}) from exc
    except Exception as exc:  # model / hardware failure
        raise HTTPException(status_code=500, detail={"error": f"inference failed: {exc}"}) from exc

    return JSONResponse(content=result)


_predict_lock = threading.Lock()  # the model is single-tenant; serialize concurrent calls


async def run_inference(state: Any, questions: dict, model: str | None = None, lang: str | None = None) -> dict:
    """Run prediction off the event loop so slow inference never blocks the server."""
    import anyio

    def _predict() -> dict:
        with _predict_lock:
            return service.predict(state, questions, model=model, lang=lang)

    return await anyio.to_thread.run_sync(_predict)


if __name__ == "__main__":
    import uvicorn

    host = os.environ.get("LAYA_HOST", "0.0.0.0")
    port = int(os.environ.get("LAYA_PORT", "8000"))
    print(f"Serving Laya ({service.name}) on http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="info")
