"""FastAPI application entry point for CodeReviewer.

Run from the ``backend`` directory:

    .venv/Scripts/python.exe -m uvicorn app.main:app --reload --port 8000

Interactive API docs are then available at http://localhost:8000/docs.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import config
from app.data import problems as problem_data
from app.db import check_database
from app.routes import auth, problems, progress, reviews, saved_code, submissions
from app.schemas.submission import HealthResponse

logging.basicConfig(
    level=logging.DEBUG if config.DEBUG else logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
logger = logging.getLogger("codereviewer")


@asynccontextmanager
async def lifespan(_: FastAPI):
    if config.llm_enabled():
        logger.info("AI review: provider chain %s.", config.llm_model())
    else:
        logger.warning(
            "AI review: neither GEMINI_API_KEY nor GROQ_API_KEY is set - using "
            "the built-in rule-based reviewer. Set a key in backend/.env to "
            "enable the LLM."
        )
    logger.info("Loaded %d problems.", len(problem_data.list_problems()))

    # Sign-in is mandatory in Phase 2, so the database and Clerk are both
    # load-bearing. Startup reports on them loudly but does NOT abort: a
    # crashed process makes /api/health and /docs unreachable, which removes
    # the very diagnostics needed to see what is wrong. Reporting beats
    # failing here.
    if not config.database_configured():
        logger.error(
            "Database: no DATABASE_URL configured - every authenticated "
            "request will fail. Set it in backend/.env."
        )
    else:
        ok, error = check_database()
        if ok:
            logger.info("Database: connected.")
        else:
            logger.error(
                "Database: cannot reach %s - %s. Is the PostgreSQL service "
                "running and are the credentials in backend/.env correct?",
                config.DATABASE_URL.rsplit("@", 1)[-1],
                error,
            )

    if not config.auth_configured():
        logger.error(
            "Auth: no CLERK_SECRET_KEY configured - nobody can sign in. "
            "Set it in backend/.env."
        )
    else:
        logger.info(
            "Auth: Clerk configured, accepting tokens from %s.",
            ", ".join(config.CLERK_AUTHORIZED_PARTIES),
        )

    # Execution sandbox. Both states are reported, because both are silent
    # failure modes: a dead Docker daemon makes every run fail with a message
    # about the sandbox, and the subprocess backend makes every run succeed
    # while quietly executing student code on this machine.
    backend = config.runner_backend()
    if backend == "docker":
        docker_ok, docker_error = config.check_docker()
        if docker_ok:
            logger.info("Execution: Docker sandbox ready (image %s).", config.RUNNER_IMAGE)
        else:
            logger.error(
                "Execution: RUNNER_BACKEND=docker but the daemon is unreachable - "
                "%s. Every submission will fail. Start Docker Desktop, or set "
                "RUNNER_BACKEND=subprocess in backend/.env to run without a sandbox.",
                docker_error,
            )
    else:
        logger.warning(
            "Execution: RUNNER_BACKEND=subprocess - student code runs directly on "
            "this machine with no container isolation. Intended only as the "
            "fallback when Docker is unavailable."
        )

    yield


app = FastAPI(
    title="CodeReviewer API",
    description=(
        "Backend for the CodeReviewer MVP: problem catalogue, Python test "
        "execution, and AI code review."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

# The Vite dev server runs on a different origin, so the API must allow it.
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(problems.router)
app.include_router(submissions.router)
app.include_router(reviews.router)
app.include_router(progress.router)
app.include_router(saved_code.router)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Last-resort handler so the frontend always receives JSON, never HTML."""
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "The server hit an unexpected error. Please try again."},
    )


@app.get("/api/health", response_model=HealthResponse, tags=["meta"])
def health() -> HealthResponse:
    """Readiness probe and demo aid.

    Reports whether the LLM is configured, whether the database is reachable,
    whether Clerk is set up, and which execution backend will run submissions.
    Declared with ``def`` (not ``async def``) so the synchronous database ping
    runs in a worker thread.
    """
    db_ok, db_error = (False, "DATABASE_URL is not configured")
    if config.database_configured():
        db_ok, db_error = check_database()

    backend = config.runner_backend()
    # Only probe Docker when it is actually the backend. Running the probe for
    # the subprocess backend would add a subprocess spawn to every health check
    # to answer a question nobody asked.
    docker_ok, docker_error = (False, None)
    if backend == "docker":
        docker_ok, docker_error = config.check_docker()

    return HealthResponse(
        status="ok",
        llm_configured=config.llm_enabled(),
        llm_model=config.llm_model(),
        problems=len(problem_data.list_problems()),
        database_configured=config.database_configured(),
        database_ok=db_ok,
        database_error=None if db_ok else db_error,
        auth_configured=config.auth_configured(),
        runner_backend=backend,
        runner_image=config.RUNNER_IMAGE if backend == "docker" else None,
        docker_ok=docker_ok,
        docker_error=None if docker_ok else docker_error,
    )


@app.get("/", include_in_schema=False)
def root() -> dict[str, str]:
    return {
        "service": "CodeReviewer API",
        "docs": "/docs",
        "health": "/api/health",
    }
