"""Ghost Cursor Cloud Orchestrator — FastAPI Application.

This is the hosted AI reasoning engine that processes user requests,
runs the Google ADK agent loop, and manages multi-turn run state.
"""

import hashlib
import logging
import os
import re
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .models import CreateRunRequest, ContinueRunRequest, RunResponse, SuggestionsRequest, SuggestionsResponse
from .run_manager import RunManager
from .storage.memory import MemoryRunStore
from .llm.provider import MockLLMProvider

# Load .env from orchestrator directory first, fallback to current working directory
_env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
if os.path.exists(_env_path):
    load_dotenv(_env_path)
else:
    load_dotenv()

logger = logging.getLogger("ghost_cursor")
logging.basicConfig(level=logging.INFO)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MAX_BODY_BYTES = 64 * 1024  # 64 KiB
RATE_LIMIT_WINDOW = 60  # seconds
RATE_LIMIT_MAX = 60  # requests per window

# Server-secret map: credential -> tenant_id
# In production, loaded from Secret Manager
TENANT_CREDENTIALS: dict[str, str] = {}
_raw = os.getenv("GHOST_TENANT_CREDENTIALS", "")
if _raw:
    for pair in _raw.split(","):
        if ":" in pair:
            cred, tid = pair.split(":", 1)
            TENANT_CREDENTIALS[cred.strip()] = tid.strip()

# Always include a dev key for local testing
DEV_KEY = os.getenv("GHOST_DEV_API_KEY", "dev-test-key-minimum-32-characters-long")
if DEV_KEY:
    TENANT_CREDENTIALS[DEV_KEY] = os.getenv("GHOST_DEV_TENANT_ID", "shophive_demo")

SUBJECT_PATTERN = re.compile(r"^[a-zA-Z0-9_.:@\-]+$")

# ---------------------------------------------------------------------------
# Instance-local rate limiter (not distributed)
# ---------------------------------------------------------------------------
_rate_buckets: dict[str, list[float]] = {}


def _check_rate_limit(key: str) -> bool:
    """Returns True if the request should be rate-limited."""
    now = time.time()
    bucket = _rate_buckets.setdefault(key, [])
    # Purge old entries
    bucket[:] = [t for t in bucket if now - t < RATE_LIMIT_WINDOW]
    if len(bucket) >= RATE_LIMIT_MAX:
        return True
    bucket.append(now)
    return False


# Module-level instances for direct access / tests
run_store: Optional[Any] = None
vertex_client: Optional[Any] = None


def init_globals():
    """Ensure global services are initialized even if lifespan wasn't triggered (e.g. tests)"""
    global run_store, vertex_client
    ghost_env = os.getenv("GHOST_ENV", "development").lower()
    ghost_provider = os.getenv("GHOST_PROVIDER")
    ghost_store = os.getenv("GHOST_STORE", "memory")

    if ghost_provider and ghost_provider not in ("mock", "vertex", "adk"):
        raise RuntimeError(f"GHOST_PROVIDER must be 'mock', 'vertex', or 'adk', got: {ghost_provider!r}")

    if ghost_provider == "adk":
        project_id = os.getenv("GCP_PROJECT_ID") or os.getenv("GOOGLE_CLOUD_PROJECT")
        if not project_id:
            raise RuntimeError("GCP_PROJECT_ID or GOOGLE_CLOUD_PROJECT is required when GHOST_PROVIDER is 'adk'")
        os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "TRUE"
        os.environ["GOOGLE_CLOUD_PROJECT"] = project_id
        if os.getenv("GCP_LOCATION") and not os.getenv("GOOGLE_CLOUD_LOCATION"):
            os.environ["GOOGLE_CLOUD_LOCATION"] = os.environ["GCP_LOCATION"]

    if ghost_store and ghost_store not in ("memory", "postgres"):
        raise RuntimeError(f"GHOST_STORE must be 'memory' or 'postgres', got: {ghost_store!r}")

    if ghost_env == "production":
        if ghost_provider == "mock":
            raise RuntimeError("mock provider is not allowed in production")
        if ghost_store == "memory":
            raise RuntimeError("memory store is not allowed in production")

    if ghost_store == "postgres" and not os.getenv("DATABASE_URL"):
        raise RuntimeError("DATABASE_URL is required when GHOST_STORE is 'postgres'")

    if ghost_provider == "vertex" and not os.getenv("GCP_PROJECT_ID"):
        raise RuntimeError("GCP_PROJECT_ID is required when GHOST_PROVIDER is 'vertex'")

    if run_store is None:
        run_store = MemoryRunStore()

    if vertex_client is None:
        if ghost_provider == "vertex":
            from .llm.gemini import GeminiProvider
            project_id = os.environ["GCP_PROJECT_ID"]
            location = os.getenv("GCP_LOCATION", "us-central1")
            model = os.getenv("GHOST_MODEL", "gemini-2.0-flash")
            vertex_client = GeminiProvider(project=project_id, location=location, model=model)
        elif ghost_provider == "adk":
            from .llm.adk import ADKProvider
            project_id = os.getenv("GCP_PROJECT_ID") or os.getenv("GOOGLE_CLOUD_PROJECT")
            location = os.getenv("GCP_LOCATION") or os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
            model = os.getenv("GHOST_MODEL", "gemini-2.0-flash")
            vertex_client = ADKProvider(project=project_id, location=location, model=model)
        elif ghost_provider == "mock":
            from .llm.provider import MockLLMProvider
            vertex_client = MockLLMProvider()


# ---------------------------------------------------------------------------
# App lifecycle
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize stores and providers on startup."""
    init_globals()
    store = getattr(app.state, "store", None) or run_store or MemoryRunStore()
    from .llm.provider import get_llm_provider
    provider = getattr(app.state, "provider", None) or vertex_client or get_llm_provider()
    app.state.run_manager = RunManager(store=store, provider=provider)
    logger.info(f"Ghost Cursor Orchestrator started (Store: {store.__class__.__name__}, Provider: {provider.__class__.__name__})")
    yield
    if provider and hasattr(provider, "close"):
        await provider.close()
    logger.info("Ghost Cursor Orchestrator shutting down")


app = FastAPI(
    title="Ghost Cursor Cloud Orchestrator",
    version="0.1.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------
@app.middleware("http")
async def security_middleware(request: Request, call_next):
    """Enforce security headers, body limits, and Origin rejection."""
    # Reject browser-origin requests to the hosted API (defense in depth)
    if request.url.path.startswith("/v1/"):
        origin = request.headers.get("origin")
        if origin:
            return JSONResponse(
                status_code=403,
                content={"error": "Direct browser access is not permitted."},
                headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
            )

    # Body size limit
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > MAX_BODY_BYTES:
        return JSONResponse(
            status_code=413,
            content={"error": "Request body exceeds 64 KiB limit."},
        )

    response: Response = await call_next(request)

    # Security headers on all responses
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"

    return response


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------
def _authenticate(request: Request) -> str:
    """Extract and validate tenant from Bearer credential. Returns tenant_id."""
    auth = request.headers.get("authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid authorization.")

    credential = auth[7:]
    if len(credential) < 32:
        raise HTTPException(status_code=401, detail="Invalid credential.")

    tenant_id = TENANT_CREDENTIALS.get(credential)
    if tenant_id is None:
        raise HTTPException(status_code=401, detail="Invalid credential.")

    return tenant_id


def _get_subject(request: Request) -> str:
    """Extract and validate X-Ghost-Subject header."""
    subject = request.headers.get("x-ghost-subject", "")
    if not subject or len(subject) > 120 or not SUBJECT_PATTERN.match(subject):
        raise HTTPException(status_code=400, detail="Missing or invalid X-Ghost-Subject.")
    return subject


# ---------------------------------------------------------------------------
# Health endpoint (no auth)
# ---------------------------------------------------------------------------
@app.get("/health")
async def health():
    return {"status": "ok", "service": "ghost-cursor-orchestrator"}


# ---------------------------------------------------------------------------
# Create Run
# ---------------------------------------------------------------------------
@app.post("/v1/runs", response_model=RunResponse)
async def create_run(request: Request):
    """Create a new agent run from a user message + context."""
    tenant_id = _authenticate(request)
    subject = _get_subject(request)

    if _check_rate_limit(tenant_id):
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Try again later.")

    body = await request.json()

    try:
        req = CreateRunRequest(**body)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid request: {str(e)[:200]}")

    run_manager: RunManager = request.app.state.run_manager
    result = await run_manager.create_run(tenant_id, subject, req)
    return result


# ---------------------------------------------------------------------------
# Continue Run
# ---------------------------------------------------------------------------
@app.post("/v1/runs/{run_id}/continue", response_model=RunResponse)
async def continue_run(run_id: str, request: Request):
    """Continue an existing run with action results, answers, or cancellation."""
    tenant_id = _authenticate(request)
    subject = _get_subject(request)

    if _check_rate_limit(tenant_id):
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Try again later.")

    # Validate run_id as UUID
    try:
        uuid.UUID(run_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid run ID format.")

    body = await request.json()

    try:
        req = ContinueRunRequest(**body)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid request: {str(e)[:200]}")

    run_manager: RunManager = request.app.state.run_manager
    result = await run_manager.continue_run(run_id, tenant_id, subject, req)
    return result


# ---------------------------------------------------------------------------
# Suggestions Endpoint
# ---------------------------------------------------------------------------
@app.post("/v1/suggestions", response_model=SuggestionsResponse)
async def get_suggestions(request: Request):
    """Generate page-contextual suggested questions for quick prompt chips."""
    tenant_id = _authenticate(request)

    if _check_rate_limit(tenant_id):
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Try again later.")

    body = await request.json()
    try:
        req = SuggestionsRequest(**body)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid request: {str(e)[:200]}")

    from .tenant_config import get_tenant_config, extract_brain_config
    brain_cfg = extract_brain_config(req.brain)
    req_overrides = req.clientConfig.model_dump(exclude_none=True) if getattr(req, "clientConfig", None) else {}
    effective_config = {**brain_cfg, **req_overrides}
    tenant_cfg = get_tenant_config(tenant_id, effective_config)

    run_manager: RunManager = request.app.state.run_manager
    provider = run_manager.provider

    suggestions = await provider.generate_suggestions(
        page=req.page,
        brain=req.brain,
        targets=req.availableTargets,
        count=req.count,
        client_config=tenant_cfg,
    )

    return SuggestionsResponse(
        protocolVersion="1",
        page=req.page,
        suggestions=suggestions,
    )


