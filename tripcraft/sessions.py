import uuid
import asyncio
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from tripcraft.prompts import SYSTEM_PROMPT

@dataclass
class Session:
    id: str
    messages: list = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_active: datetime = field(default_factory=datetime.utcnow)

    def add_message(self, msg: dict):
        self.messages.append(msg)
        self.last_active = datetime.utcnow()

    def full_messages(self) -> list:
        """Combine system prompt with message history, injecting current date/time context."""
        now = datetime.now()
        current_date_str = f"Current Year: {now.year}\nToday's Date: {now.strftime('%A, %B %d, %Y')}\nCurrent Local Time: {now.strftime('%I:%M %p')}"
        system_content = f"{SYSTEM_PROMPT}\n\n## CURRENT TIME CONTEXT (Crucial for travel planning dates):\n{current_date_str}"
        return [{"role": "system", "content": system_content}] + self.messages

    def is_expired(self, ttl: int) -> bool:
        return (datetime.utcnow() - self.last_active) > timedelta(minutes=ttl)

    def to_response(self, tools_available: list) -> dict:
        # Check which tools are actually available based on config/keys
        # (e.g. if we have Amadeus keys but not Foursquare keys)
        all_tools = ["search_flights", "search_hotels", "get_weather_forecast", "search_places", "geocode", "search_transportation", "search_web"]
        degraded = [t for t in all_tools if t not in tools_available]
        
        return {
            "session_id": self.id,
            "created_at": self.created_at.isoformat() + "Z",
            "expires_in_minutes": 30,
            "message_count": len(self.messages),
            "tools_available": tools_available,
            "tools_degraded": degraded,
        }

class SessionManager:
    def __init__(self, ttl_minutes: int = 30):
        self._store: dict[str, Session] = {}
        self._ttl = ttl_minutes
        self._lock = asyncio.Lock()

    def create(self) -> Session:
        s = Session(id=str(uuid.uuid4()))
        self._store[s.id] = s
        return s

    def get_or_create(self, session_id: str | None) -> Session:
        if session_id and session_id in self._store:
            s = self._store[session_id]
            s.last_active = datetime.utcnow()
            return s
        return self.create()

    def get(self, session_id: str) -> Session:
        if session_id not in self._store:
            raise KeyError(session_id)
        return self._store[session_id]

    async def delete(self, session_id: str):
        async with self._lock:
            self._store.pop(session_id, None)

    @property
    def active_count(self) -> int:
        return len(self._store)

    async def cleanup_loop(self, interval: int = 60):
        """Background coroutine to periodically evict expired idle sessions."""
        while True:
            await asyncio.sleep(interval)
            async with self._lock:
                expired = [
                    sid for sid, s in self._store.items()
                    if s.is_expired(self._ttl)
                ]
                for sid in expired:
                    del self._store[sid]
