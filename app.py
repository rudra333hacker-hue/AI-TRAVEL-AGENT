import asyncio
import logging
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from contextlib import asynccontextmanager

from tripcraft.config import Config
from tripcraft.sessions import SessionManager
from tripcraft.agent import TripCraftAgent
from tripcraft.llm import LLMClient
from tripcraft.tools import ToolRegistry
from tripcraft.models import ChatRequest, SessionResponse, HealthResponse

# Set up logging format and level
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("tripcraft")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ──
    logger.info("Initializing TripCraft AI v4.0 Services...")
    try:
        config = Config()
    except RuntimeError as e:
        logger.error(f"Configuration initialization failed: {e}")
        # We don't crash startup immediately so the health check can run,
        # but subsequent LLM/tool initialization will catch this.
        config = None

    app.state.config = config
    
    if config:
        app.state.llm = LLMClient(config)
        app.state.tools = ToolRegistry(config)
        app.state.sessions = SessionManager(ttl_minutes=config.session_ttl)
        # Background: evict expired sessions
        cleanup_task = asyncio.create_task(app.state.sessions.cleanup_loop())
        logger.info("TripCraft AI startup complete. Tools registered: %s", app.state.tools.available_names)
    else:
        app.state.llm = None
        app.state.tools = None
        app.state.sessions = SessionManager(ttl_minutes=30)
        cleanup_task = asyncio.create_task(app.state.sessions.cleanup_loop())
        logger.warning("TripCraft started in DEGRADED mode (Config could not be loaded)")

    yield
    
    # ── Shutdown ──
    logger.info("Shutting down TripCraft AI Services...")
    cleanup_task.cancel()
    if config and app.state.llm:
        await app.state.llm.close()
    logger.info("Shutdown complete.")

app = FastAPI(
    title="TripCraft AI",
    version="4.0.0",
    description="AI-powered travel planning API with real-time data",
    lifespan=lifespan,
)

# ── CORS Middleware: allow web frontends to connect ──
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.post("/api/chat")
async def chat(req: ChatRequest):
    if not app.state.config or not app.state.llm:
        raise HTTPException(
            status_code=500,
            detail="NVIDIA_API_KEY is not configured on the server. Please check the server .env configuration."
        )

    sessions = app.state.sessions
    session = sessions.get_or_create(req.session_id)

    agent = TripCraftAgent(
        llm=app.state.llm,
        tools=app.state.tools,
        session=session,
    )

    async def sse_generator():
        try:
            async for event in agent.chat_stream(req.message):
                yield f"event: {event.type}\ndata: {event.json()}\n\n"
        except Exception as e:
            logger.exception("Error in SSE chat generator")
            import json
            yield f"event: error\ndata: {json.dumps({'message': str(e)})}\n\n"

    return StreamingResponse(sse_generator(), media_type="text/event-stream")

@app.post("/api/sessions", response_model=SessionResponse)
async def create_session():
    session = app.state.sessions.create()
    available_tools = app.state.tools.available_names if app.state.tools else []
    return session.to_response(available_tools)

@app.get("/api/sessions/{session_id}", response_model=SessionResponse)
async def get_session(session_id: str):
    try:
        session = app.state.sessions.get(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")
    available_tools = app.state.tools.available_names if app.state.tools else []
    return session.to_response(available_tools)

@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    app.state.sessions.delete(session_id)
    return {"status": "deleted", "session_id": session_id}

@app.get("/api/health", response_model=HealthResponse)
async def health():
    if not app.state.config or not app.state.llm:
        return {
            "status": "unconfigured",
            "version": "4.0.0",
            "llm": {"status": "disconnected", "error": "NVIDIA_API_KEY is missing"},
            "tools": {},
            "active_sessions": app.state.sessions.active_count,
        }

    return {
        "status": "healthy",
        "version": "4.0.0",
        "llm": app.state.llm.status(),
        "tools": app.state.tools.status(),
        "active_sessions": app.state.sessions.active_count,
    }
