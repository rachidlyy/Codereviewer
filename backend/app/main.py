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
from app.routes import problems, reviews, submissions
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

app.include_router(problems.router)
app.include_router(submissions.router)
app.include_router(reviews.router)


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
    """Readiness probe and demo aid - reports whether the LLM is configured."""
    return HealthResponse(
        status="ok",
        llm_configured=config.llm_enabled(),
        llm_model=config.llm_model(),
        problems=len(problem_data.list_problems()),
    )


@app.get("/", include_in_schema=False)
def root() -> dict[str, str]:
    return {
        "service": "CodeReviewer API",
        "docs": "/docs",
        "health": "/api/health",
    }
