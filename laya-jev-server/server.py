"""HTTP API server for Laya — Jev-compatible typed decisions, served by laya.Router.

Laya: https://github.com/NandhaKishorM/laya (Apache 2.0), v0.3.3. Three checkpoints;
a Router picks the right one per request, or one checkpoint can be pinned:

    english          convaiinnovations/laya                  421M  512 tok  English
    multilingual     convaiinnovations/laya-multilingual     322M  1024 tok 100+ langs
    typed-decisions  convaiinnovations/laya-typed-decisions  421M  1024 tok fine-tuned

Request (Jev-compatible):
    POST /v1/decisions
    {
      "model": "laya",     # optional; known checkpoint names are honored, anything
                           # else (e.g. "typesafe/jev-1.13") is ignored, never a 422
      "lang": "en",        # optional; pin language instead of auto-detection
      "state": "text or dict",
      "questions": {
        "is_urgent":   {"type": "noul",   "instructions": "..."},
        "department":  {"type": "choice", "instructions": "...", "criteria": {...}},
        "frustration": {"type": "score",  "instructions": "...", "criteria": [...]}
      }
    }

Response:
    {
      "model": "laya",
      "answers": {...},
      "routing": {"model": "english", "repo": "convaiinnovations/laya", "reason": "..."},
      "usage": {"input_tokens": 128, "output_tokens": 0}
    }

Endpoints:
    POST /v1/decisions    (also POST /decisions, Jev alias)
    GET  /health          mode, loaded checkpoints
    GET  /route           dry-run the routing decision (no model load, no inference)

Modes (chosen by LAYA_MODEL at boot):
    unset / local dir    router mode — per-request routing; a ./model directory is
                         attached as the "english" checkpoint.
    "typed-decisions", "english", "multilingual", an alias, or a repo id under the
    convaiinnovations namespace
                         pinned mode — that checkpoint answers every request, no
                         routing. Known names resolve through the cached bundle
                         (convaiinnovations/laya), so no separate download is needed.
                         Unknown repo ids load directly; if the pinned weights are
                         unusable, the pin is dropped with a loud warning and router
                         mode takes over (something always answers).

Run:
    python server.py
    LAYA_MODEL="typed-decisions" python server.py

Environment:
    LAYA_MODEL       checkpoint name/alias, hub repo id (pin), or local dir
    LAYA_DEVICE      "cpu", "cuda", ... (default: torch decides)
    LAYA_PRELOAD     "1" = build all checkpoints at startup (router mode)
    LAYA_MAX_LOADED  checkpoints kept resident (default 1, LRU eviction)
    LAYA_DEFAULT     checkpoint for ambiguous routes (default "english")
    HF_HOME          HF cache location (on "ml": /home/mod/.huggingface)
    HF_HUB_OFFLINE   "1" = never contact the hub; cached checkpoints only

Requires: pip install fastapi uvicorn laya
"""

from __future__ import annotations

import os
import threading
from contextlib import asynccontextmanager
from typing import Any

try:
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import JSONResponse
    from pydantic import BaseModel, Field
except ImportError as exc:  # pragma: no cover
    raise SystemExit("server.py requires FastAPI: pip install fastapi uvicorn") from exc

VALID_QTYPES = ("choice", "score", "noul")
LOCAL_MODEL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "model")


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def _resolve_checkpoint_name(repo_or_name: str) -> str | None:
    """Map a LAYA_MODEL value onto a checkpoint NAME the bundle cache serves.

    Accepts checkpoint names, aliases ("laya", "multi", ...) and repo ids under the
    convaiinnovations namespace ("convaiinnovations/laya-typed-decisions" -> the
    bundle's typed-decisions subfolder). Returns None for unknown repo ids.
    """
    from laya.router import normalise_name

    for candidate in (repo_or_name, repo_or_name.split("/")[-1]):
        try:
            return normalise_name(candidate)
        except (ValueError, KeyError):
            continue
    return None


# ---------------------------------------------------------------------------
# Service: two modes over one predict() surface
# ---------------------------------------------------------------------------


class LayaService:
    """Laya decision model behind one predict() surface.

    router mode  -- LAYA_MODEL unset or a local directory: laya.Router routes each
                    request (script/language detection, explicit overrides); a local
                    checkpoint directory is attached as the "english" slot.
    pinned mode  -- LAYA_MODEL set to a checkpoint name/alias/repo id: that checkpoint
                    answers every request; no routing, nothing else is loaded.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._model: Any = None            # Router (both modes) or Agent (unknown-repo pin)
        self._pinned_name: str | None = None
        env_model = os.environ.get("LAYA_MODEL")
        self.pinned_repo: str | None = env_model if (env_model and not os.path.isdir(env_model)) else None
        self.local_dir: str | None = (
            env_model if (env_model and os.path.isdir(env_model))
            else (LOCAL_MODEL_DIR if os.path.isdir(LOCAL_MODEL_DIR) else None)
        )
        self._name = env_model or (LOCAL_MODEL_DIR if os.path.isdir(LOCAL_MODEL_DIR) else "convaiinnovations/laya")

    # -- identity ----------------------------------------------------------

    @property
    def mode(self) -> str:
        return "pinned" if self.pinned_repo else "router"

    @property
    def name(self) -> str:
        return self._name if os.path.isdir(self._name) else "laya"

    # -- loading -----------------------------------------------------------

    def _build(self) -> Any:
        """Lazily build the model, thread-safe; first caller pays the load."""
        if self._model is not None:
            return self._model
        with self._lock:
            if self._model is None:
                import laya

                if self.pinned_repo:
                    router = laya.Router(
                        device=os.environ.get("LAYA_DEVICE") or None,
                        max_loaded=max(1, int(os.environ.get("LAYA_MAX_LOADED", "1"))),
                    )
                    self._pinned_name = _resolve_checkpoint_name(self.pinned_repo)
                    if self._pinned_name:
                        router.load(self._pinned_name)  # fail fast if unusable
                    else:
                        # unknown repo id: load directly as a single Agent
                        self._model = laya.load(self.pinned_repo, device=os.environ.get("LAYA_DEVICE") or None)
                        return self._model
                    self._model = router
                else:
                    router = laya.Router(
                        device=os.environ.get("LAYA_DEVICE") or None,
                        max_loaded=int(os.environ.get("LAYA_MAX_LOADED", "1")),
                        default=os.environ.get("LAYA_DEFAULT", "english"),
                    )
                    if self.local_dir:
                        router.attach("english", laya.load(self.local_dir))
                    if not _env_flag("HF_HUB_OFFLINE"):
                        # fresh user: fetch all three checkpoints at startup, so the
                        # first decision never waits (offline: serve cached only)
                        router.preload()
                    self._model = router
        return self._model

    # -- inference ---------------------------------------------------------

    def predict(self, state: Any, questions: dict, model: str | None = None, lang: str | None = None) -> dict:
        if self.pinned_repo:
            try:
                built = self._build()
                if self._pinned_name:
                    result = built.predict(state, questions, model=self._pinned_name)
                    result["routing"] = {
                        "model": self._pinned_name,
                        "repo": self.pinned_repo,
                        "reason": f"pinned by LAYA_MODEL={self.pinned_repo}; no routing",
                    }
                else:
                    result = built.system_one(state, questions)
                    result["routing"] = {
                        "model": "pinned",
                        "repo": self.pinned_repo,
                        "reason": f"pinned by LAYA_MODEL={self.pinned_repo}; no routing",
                    }
                result["model"] = self.name
                return result
            except Exception as exc:
                # pinned weights unusable (e.g. a partial download: snapshot exists,
                # model.safetensors missing). Serving nothing forever is worse than
                # degrading: drop the pin loudly and let the router take over.
                print(
                    f"\nWARNING: pinned checkpoint {self.pinned_repo!r} failed to load ({exc}).\n"
                    "         PIN DROPPED -- serving the cached checkpoint in router mode.\n",
                    flush=True,
                )
                self.pinned_repo = None
                self._pinned_name = None
                self._model = None
        result = self._build().predict(state, questions, model=_known_checkpoint(model), lang=lang or None)
        result["model"] = self.name
        return result

    def route(self, state: Any, questions: dict, model: str | None = None, lang: str | None = None) -> dict:
        """The routing decision for a request, without loading or running anything."""
        if self.pinned_repo:
            return {
                "model": self._pinned_name or "pinned",
                "repo": self.pinned_repo,
                "reason": f"pinned by LAYA_MODEL={self.pinned_repo}; no routing",
            }
        return dict(self._build().route(state, questions, model=_known_checkpoint(model), lang=lang or None))

    @property
    def loaded_checkpoints(self) -> list[str]:
        model = self._model
        if model is None:
            return []
        loaded = getattr(model, "loaded", None)  # Router has .loaded; a pinned Agent does not
        return list(loaded) if loaded is not None else ["pinned"]


def _known_checkpoint(model: str | None) -> str | None:
    """Checkpoint names the Router knows pass through; everything else is ignored.

    "model" exists for Jev compatibility and clients send their own values
    ("typesafe/jev-1.13"); an unknown name must degrade to auto-routing, not 422.
    """
    if not model:
        return None
    from laya.router import normalise_name

    try:
        return normalise_name(model)
    except (ValueError, KeyError):
        return None


service = LayaService()

# ---------------------------------------------------------------------------
# Fail fast at startup: a pin that cannot be served must say so immediately
# ---------------------------------------------------------------------------


def _prefer_ipv4() -> None:
    """Force IPv4 for DNS resolution in this process.

    On some hosts (ml) the IPv6 route to the HF CDN black-holes: connections sit in
    SYN-SENT forever and downloads stall silently. Preferring AF_INET makes downloads
    work. Harmless on IPv4-only hosts.
    """
    import socket

    original = socket.getaddrinfo

    def prefer_ipv4(*args: Any, **kwargs: Any):
        results = original(*args, **kwargs)
        ipv4 = [r for r in results if r[0] == socket.AF_INET]
        return ipv4 or results

    socket.getaddrinfo = prefer_ipv4


def _cache_has_weights(repo_id: str) -> bool:
    """True if the HF cache on disk holds a downloaded snapshot with weights.

    Pure filesystem check (no hub import, no network): refs/main must resolve to a
    snapshot that contains a model.safetensors somewhere in its tree.
    """
    base = os.environ.get("HF_HOME") or os.path.join(os.path.expanduser("~"), ".cache", "huggingface")
    d = os.path.join(base, "hub", "models--" + repo_id.replace("/", "--"))
    try:
        with open(os.path.join(d, "refs", "main")) as f:
            rev = f.read().strip()
    except OSError:
        return False
    snap = os.path.join(d, "snapshots", rev)
    if not os.path.isdir(snap):
        return False
    for _root, _dirs, files in os.walk(snap):
        if "model.safetensors" in files:
            return True
    return False


def _check_pinned_checkpoint() -> None:
    """Startup model contract (cache-first):

    - model already on disk      -> USE IT, never re-download, never even ask the hub
    - model missing, online      -> download it now (pinned: that one; unpinned: all 3)
    - model missing, offline     -> impossible: warn loudly, serve what exists
    """
    offline_env = _env_flag("HF_HUB_OFFLINE")
    bundle_cached = _cache_has_weights("convaiinnovations/laya")

    if bundle_cached:
        # weights are on disk: freeze the cache for this process -- no hub checks,
        # no re-downloads, whatever is downloaded is what gets served
        os.environ["HF_HUB_OFFLINE"] = "1"
        # NOTE: _pinned_name is not resolved yet (that happens in _build, which imports
        # torch-heavy laya); print the raw value the user configured instead.
        if service.pinned_repo:
            print(f"using cached checkpoint ({service.pinned_repo})", flush=True)
        else:
            print("using cached checkpoints (bundle convaiinnovations/laya)", flush=True)
        return

    if offline_env:
        # nothing on disk and downloading forbidden: the pin cannot be honored
        if service.pinned_repo:
            print(
                f"\nWARNING: LAYA_MODEL={service.pinned_repo!r} is not downloaded and"
                " downloading is disabled by HF_HUB_OFFLINE=1.\n"
                "         PIN IGNORED -- router mode will try to serve what exists.\n",
                flush=True,
            )
            service.pinned_repo = None
            service._pinned_name = None
        return

    # online and not cached: download now, visibly, before serving
    _prefer_ipv4()
    try:
        service._build()
        # from now on this process never needs the hub again
        os.environ["HF_HUB_OFFLINE"] = "1"
        if service.pinned_repo:
            print(f"pinned checkpoint ready: {service._pinned_name} ({service.pinned_repo})", flush=True)
        else:
            print(f"all checkpoints ready: {', '.join(service.loaded_checkpoints)}", flush=True)
    except Exception as exc:
        if service.pinned_repo:
            print(
                f"\nWARNING: pinned checkpoint {service.pinned_repo!r} failed to load ({exc}).\n"
                 "         PIN DROPPED -- serving the cached checkpoint in router mode.\n",
                flush=True,
            )
            service.pinned_repo = None
            service._pinned_name = None
            service._model = None
        else:
            print(
                f"\nWARNING: checkpoint download failed ({exc}).\n"
                 "         Serving cached checkpoints only; missing ones load on demand.\n",
                flush=True,
            )
            service._model = None


@asynccontextmanager
async def _lifespan(app: FastAPI):
    _check_pinned_checkpoint()
    yield


app = FastAPI(
    title="Laya Decisions API",
    description="Jev-compatible typed decision API for Laya",
    version="1.1.0",
    lifespan=_lifespan,
)

# ---------------------------------------------------------------------------
# Request model / validation
# ---------------------------------------------------------------------------


class QuestionDef(BaseModel):
    type: str = Field(description='One of "choice", "score", "noul"')
    instructions: str = Field(min_length=1)
    criteria: Any = Field(
        default=None,
        description="choice: {option: description} or [options]; score: ordered rubric; noul: unused",
    )


class DecisionRequest(BaseModel):
    model: str | None = Field(default=None, description='Optional checkpoint hint ("english", "multilingual", "typed-decisions")')
    lang: str | None = Field(default=None, description='Optional language code (e.g. "en", "de")')
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
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "model": service.name,
        "mode": service.mode,
        "loaded": service._model is not None,
        "checkpoints_loaded": service.loaded_checkpoints,
        **({} if service.pinned_repo else {"max_loaded": int(os.environ.get("LAYA_MAX_LOADED", "1"))}),
    }


@app.get("/route")
def route(state: Any = None, questions: dict | None = None, model: str | None = None, lang: str | None = None) -> dict:
    """Inspect the routing decision without loading or running the model."""
    return service.route(state or {}, questions or {}, model=model, lang=lang)


@app.post("/v1/decisions")
@app.post("/decisions")  # Jev-style alias
async def decisions(req: DecisionRequest) -> JSONResponse:
    validate_questions(req.questions)
    questions = {qid: q.model_dump(exclude_none=False) for qid, q in req.questions.items()}
    try:
        result = await _run_inference(req.state, questions, model=req.model, lang=req.lang)
    except ValueError as exc:  # e.g. options do not fit in head_max_len
        raise HTTPException(status_code=422, detail={"error": str(exc)}) from exc
    except Exception as exc:  # model / hardware failure
        raise HTTPException(status_code=500, detail={"error": f"inference failed: {exc}"}) from exc
    return JSONResponse(content=result)


_predict_lock = threading.Lock()  # the model is single-tenant; serialize concurrent calls


async def _run_inference(state: Any, questions: dict, model: str | None = None, lang: str | None = None) -> dict:
    """Inference in a worker thread so a slow forward pass never blocks the loop."""
    import anyio

    def _predict() -> dict:
        with _predict_lock:
            return service.predict(state, questions, model=model, lang=lang)

    return await anyio.to_thread.run_sync(_predict)


if __name__ == "__main__":
    import uvicorn

    host = os.environ.get("LAYA_HOST", "0.0.0.0")
    port = int(os.environ.get("LAYA_PORT", "8000"))
    print(f"Serving Laya ({service.name}, {service.mode} mode) on http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="info")
#
