from pydantic import BaseModel, Field
from typing import Optional, List, Dict

class ChatRequest(BaseModel):
    session_id: Optional[str] = Field(None, description="Existing session ID or omit to auto-create")
    message: str = Field(..., min_length=1, max_length=4000)

class SessionResponse(BaseModel):
    session_id: str
    created_at: str
    expires_in_minutes: int
    message_count: int
    tools_available: List[str]
    tools_degraded: List[str]

class HealthResponse(BaseModel):
    status: str
    version: str
    llm: Dict
    tools: Dict
    active_sessions: int
