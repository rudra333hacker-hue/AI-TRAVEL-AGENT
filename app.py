import os
import asyncio
import time
import logging
from collections import defaultdict
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
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

class LocalAgentConfig:
    LLM_PROVIDER = "nvidia"
    NVIDIA_MODEL = "meta/llama-3.3-70b-instruct"
    NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"

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
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── In-Memory IP-based Rate Limiter Configuration ──
RATE_LIMIT_REQUESTS = 120  # max 120 requests
RATE_LIMIT_WINDOW = 60     # per 60 seconds
client_requests = defaultdict(list)

# ── Production API Key Configuration ──
TRIPCRAFT_API_KEY = os.getenv("TRIPCRAFT_API_KEY", "")

@app.middleware("http")
async def security_and_rate_limit_middleware(request: Request, call_next):
    path = request.url.path
    
    # 1. Rate Limiting Check (Bypass static files and root dashboard)
    if not (path.startswith("/static") or path == "/" or path == "/favicon.ico"):
        client_ip = request.client.host if request.client else "unknown"
        now = time.time()
        
        timestamps = client_requests[client_ip]
        timestamps = [t for t in timestamps if now - t < RATE_LIMIT_WINDOW]
        client_requests[client_ip] = timestamps
        
        if len(timestamps) >= RATE_LIMIT_REQUESTS:
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests. Please try again later."}
            )
        client_requests[client_ip].append(now)

    # 2. X-API-Key Authorization Check
    # Only protect API routes (except the general health endpoint)
    if path.startswith("/api/") and path != "/api/health":
        if TRIPCRAFT_API_KEY:
            api_key = request.headers.get("X-API-Key")
            if api_key != TRIPCRAFT_API_KEY:
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Unauthorized: Invalid or missing X-API-Key header"}
                )

    return await call_next(request)

# Serve static files (CSS, JS, images)
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")

@app.get("/", response_class=HTMLResponse)
async def root():
    html_path = Path(__file__).parent / "static" / "index.html"
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"))

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
            async for event in agent.chat_stream(req.message, images=req.images):
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
    await app.state.sessions.delete(session_id)
    return {"status": "deleted", "session_id": session_id}

@app.get("/api/health")
async def health(request: Request, format: str = "json"):
    """Health check endpoint.
    
    Returns JSON by default. Append ?format=html to view the dashboard in a browser.
    """
    if not app.state.config or not app.state.llm:
        data = {
            "status": "unconfigured",
            "version": "4.0.0",
            "llm": {"status": "disconnected", "error": "NVIDIA_API_KEY is missing"},
            "tools": {},
            "active_sessions": app.state.sessions.active_count,
        }
    else:
        data = {
            "status": "healthy",
            "version": "4.0.0",
            "llm": app.state.llm.status(),
            "tools": app.state.tools.status(),
            "active_sessions": app.state.sessions.active_count,
        }

    if format == "html":
        return HTMLResponse(content=_health_dashboard_html(data))

    return data


def _health_dashboard_html(data: dict) -> str:
    """Render a self-contained HTML health dashboard."""
    status = data["status"]
    version = data["version"]
    active_sessions = data["active_sessions"]
    llm = data.get("llm", {})
    tools = data.get("tools", {})

    overall_color = "#10b981" if status == "healthy" else "#ef4444"
    overall_icon = "\u2705" if status == "healthy" else "\u274c"

    def status_badge(s: str) -> str:
        if s == "available":
            return f'<span class="badge badge-ok">\u2714 Available</span>'
        elif s == "unavailable":
            return f'<span class="badge badge-warn">\u26a0 Unavailable</span>'
        return f'<span class="badge badge-info">{s}</span>'

    def tool_card(name: str, info: dict) -> str:
        st = info.get("status", "unknown")
        provider = info.get("provider", "-")
        border = "#10b981" if st == "available" else ("#f59e0b" if st == "unavailable" else "#ef4444")
        return f'''
        <div class="tool-card" style="border-left: 4px solid {border};">
            <div class="tool-name">{name}</div>
            <div class="tool-provider">{provider}</div>
            <div class="tool-status">{status_badge(st)}</div>
        </div>'''

    tool_cards = "\n".join(tool_card(n, i) for n, i in tools.items())

    llm_status = llm.get("status", "disconnected")
    llm_model = llm.get("model", "-")
    llm_provider = llm.get("provider", "-")
    llm_color = "#10b981" if llm_status == "connected" else "#ef4444"
    llm_icon = "\u2705" if llm_status == "connected" else "\u274c"

    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>TripCraft AI — Health Dashboard</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
*, *::before, *::after {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    background: #0a0e1a;
    color: #f1f5f9;
    min-height: 100vh;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 24px;
}}
.container {{
    max-width: 840px;
    width: 100%;
}}
.header {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 28px;
}}
.header-left {{
    display: flex;
    align-items: center;
    gap: 12px;
}}
.header-left .logo {{
    font-size: 32px;
}}
.header-left h1 {{
    font-size: 22px;
    font-weight: 800;
    letter-spacing: -0.02em;
    background: linear-gradient(135deg, #6366f1, #8b5cf6);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
}}
.header-right {{
    text-align: right;
}}
.header-right .version {{
    font-size: 13px;
    color: #64748b;
}}
.status-hero {{
    display: flex;
    align-items: center;
    gap: 16px;
    padding: 24px 28px;
    border-radius: 16px;
    background: #111827;
    border: 1px solid rgba(99, 102, 241, 0.15);
    margin-bottom: 24px;
}}
.status-hero .icon {{ font-size: 36px; }}
.status-hero .info {{ flex: 1; }}
.status-hero .info .label {{ font-size: 12px; color: #64748b; text-transform: uppercase; letter-spacing: 0.06em; }}
.status-hero .info .value {{ font-size: 20px; font-weight: 700; color: {overall_color}; }}
.status-hero .info .sub {{ font-size: 13px; color: #94a3b8; margin-top: 2px; }}
.stats-row {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 12px;
    margin-bottom: 24px;
}}
.stat-card {{
    padding: 18px 20px;
    border-radius: 12px;
    background: #111827;
    border: 1px solid rgba(99, 102, 241, 0.1);
}}
.stat-card .stat-value {{ font-size: 28px; font-weight: 800; color: #6366f1; }}
.stat-card .stat-label {{ font-size: 12px; color: #64748b; margin-top: 4px; text-transform: uppercase; letter-spacing: 0.05em; }}
.section-title {{
    font-size: 14px;
    font-weight: 600;
    color: #94a3b8;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    margin-bottom: 12px;
}}
.tools-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
    gap: 10px;
    margin-bottom: 24px;
}}
.tool-card {{
    padding: 14px 16px;
    border-radius: 10px;
    background: #111827;
    border: 1px solid rgba(99, 102, 241, 0.1);
}}
.tool-card .tool-name {{ font-size: 14px; font-weight: 600; color: #f1f5f9; }}
.tool-card .tool-provider {{ font-size: 12px; color: #64748b; margin-top: 2px; }}
.tool-card .tool-status {{ margin-top: 8px; }}
.badge {{
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 3px 10px;
    border-radius: 20px;
    font-size: 11px;
    font-weight: 500;
}}
.badge-ok {{ background: rgba(16, 185, 129, 0.1); color: #10b981; border: 1px solid rgba(16, 185, 129, 0.2); }}
.badge-warn {{ background: rgba(245, 158, 11, 0.1); color: #f59e0b; border: 1px solid rgba(245, 158, 11, 0.2); }}
.badge-info {{ background: rgba(99, 102, 241, 0.1); color: #6366f1; border: 1px solid rgba(99, 102, 241, 0.2); }}
.badge-err {{ background: rgba(239, 68, 68, 0.1); color: #ef4444; border: 1px solid rgba(239, 68, 68, 0.2); }}
.llm-card {{
    padding: 16px 20px;
    border-radius: 12px;
    background: #111827;
    border: 1px solid rgba(99, 102, 241, 0.1);
    margin-bottom: 24px;
    display: flex;
    align-items: center;
    justify-content: space-between;
}}
.llm-card .llm-left {{ display: flex; align-items: center; gap: 14px; }}
.llm-card .llm-icon {{ font-size: 28px; }}
.llm-card .llm-name {{ font-size: 15px; font-weight: 600; }}
.llm-card .llm-model {{ font-size: 12px; color: #64748b; margin-top: 2px; }}
.footer {{ text-align: center; font-size: 12px; color: #475569; margin-top: 16px; }}
.footer a {{ color: #6366f1; text-decoration: none; }}
.footer a:hover {{ text-decoration: underline; }}
@media (max-width: 600px) {{
    .header {{ flex-direction: column; text-align: center; gap: 8px; }}
    .header-right {{ text-align: center; }}
    .tools-grid {{ grid-template-columns: 1fr; }}
    .stats-row {{ grid-template-columns: 1fr 1fr; }}
    .llm-card {{ flex-direction: column; text-align: center; gap: 8px; }}
    .llm-card .llm-left {{ flex-direction: column; }}
}}
</style>
</head>
<body>
<div class="container">
    <div class="header">
        <div class="header-left">
            <span class="logo">\u2708\ufe0f</span>
            <h1>TripCraft AI</h1>
        </div>
        <div class="header-right">
            <div class="version">v{version}</div>
        </div>
    </div>

    <div class="status-hero">
        <span class="icon">{overall_icon}</span>
        <div class="info">
            <div class="label">System Status</div>
            <div class="value" style="text-transform: capitalize;">{status}</div>
            <div class="sub">All systems are operational</div>
        </div>
        <div style="text-align:right;font-size:20px;font-weight:800;color:{overall_color};">
            {len(tools)} tools
        </div>
    </div>

    <div class="stats-row">
        <div class="stat-card">
            <div class="stat-value">{active_sessions}</div>
            <div class="stat-label">Active Sessions</div>
        </div>
        <div class="stat-card">
            <div class="stat-value" style="color: #10b981;">{len(tools)}</div>
            <div class="stat-label">Registered Tools</div>
        </div>
        <div class="stat-card">
            <div class="stat-value" style="color: #8b5cf6;">{llm_model}</div>
            <div class="stat-label">LLM Model</div>
        </div>
    </div>

    <div class="section-title">\u2699\ufe0f LLM Connectivity</div>
    <div class="llm-card">
        <div class="llm-left">
            <span class="llm-icon">\ud83e\udd16</span>
            <div>
                <div class="llm-name">{llm_provider}</div>
                <div class="llm-model">{llm_model}</div>
            </div>
        </div>
        <div>{status_badge(llm_status)}</div>
    </div>

    <div class="section-title">\ud83e\uddf0 Tool Status</div>
    <div class="tools-grid">
        {tool_cards}
    </div>

    <div class="footer">
        TripCraft AI v{version} &mdash;
        <a href="{'/api/health'}">JSON endpoint</a> &mdash;
        <a href="{'/'}">Chat</a>
    </div>
</div>
</body>
</html>'''
    return html
