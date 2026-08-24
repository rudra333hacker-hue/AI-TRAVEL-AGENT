import uuid
import sqlite3
import json
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
    _save_callback: callable = None

    def add_message(self, msg: dict):
        self.messages.append(msg)
        self.last_active = datetime.utcnow()
        if self._save_callback:
            self._save_callback(self)

    def full_messages(self) -> list:
        """Combine system prompt with message history, injecting current date/time context."""
        now = datetime.now()
        current_date_str = f"Current Year: {now.year}\nToday's Date: {now.strftime('%A, %B %d, %Y')}\nCurrent Local Time: {now.strftime('%I:%M %p')}"
        system_content = f"{SYSTEM_PROMPT}\n\n## CURRENT TIME CONTEXT (Crucial for travel planning dates):\n{current_date_str}"
        return [{"role": "system", "content": system_content}] + self.messages

    def is_expired(self, ttl: int) -> bool:
        return (datetime.utcnow() - self.last_active) > timedelta(minutes=ttl)

    def to_response(self, tools_available: list) -> dict:
        all_tools = ["search_flights", "search_hotels", "get_weather_forecast", "search_places", "search_transportation", "search_web"]
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
    def __init__(self, ttl_minutes: int = 30, db_path: str = "sessions.db"):
        self._ttl = ttl_minutes
        self._db_path = db_path
        self._lock = asyncio.Lock()
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    messages TEXT,
                    created_at TEXT,
                    last_active TEXT
                )
            """)

    def _to_session(self, row) -> Session:
        sid, messages_json, created_at_str, last_active_str = row
        return Session(
            id=sid,
            messages=json.loads(messages_json),
            created_at=datetime.fromisoformat(created_at_str),
            last_active=datetime.fromisoformat(last_active_str),
            _save_callback=self.save,
        )

    def create(self) -> Session:
        s = Session(id=str(uuid.uuid4()), _save_callback=self.save)
        created_str = s.created_at.isoformat()
        active_str = s.last_active.isoformat()
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                "INSERT INTO sessions (id, messages, created_at, last_active) VALUES (?, ?, ?, ?)",
                (s.id, json.dumps(s.messages), created_str, active_str)
            )
        return s

    def get_or_create(self, session_id: str | None) -> Session:
        if session_id:
            try:
                s = self.get(session_id)
                s.last_active = datetime.utcnow()
                self.save(s)
                return s
            except KeyError:
                pass
        return self.create()

    def get(self, session_id: str) -> Session:
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, messages, created_at, last_active FROM sessions WHERE id = ?", (session_id,))
            row = cursor.fetchone()
            if not row:
                raise KeyError(session_id)
            return self._to_session(row)

    def save(self, session: Session):
        created_str = session.created_at.isoformat()
        active_str = session.last_active.isoformat()
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                "UPDATE sessions SET messages = ?, created_at = ?, last_active = ? WHERE id = ?",
                (json.dumps(session.messages), created_str, active_str, session.id)
            )

    async def delete(self, session_id: str):
        async with self._lock:
            with sqlite3.connect(self._db_path) as conn:
                conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))

    @property
    def active_count(self) -> int:
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM sessions")
            return cursor.fetchone()[0]

    async def cleanup_loop(self, interval: int = 60):
        """Background coroutine to periodically evict expired idle sessions from SQLite."""
        while True:
            await asyncio.sleep(interval)
            try:
                async with self._lock:
                    now = datetime.utcnow()
                    threshold = (now - timedelta(minutes=self._ttl)).isoformat()
                    with sqlite3.connect(self._db_path) as conn:
                        cursor = conn.cursor()
                        cursor.execute("SELECT COUNT(*) FROM sessions WHERE last_active < ?", (threshold,))
                        expired_count = cursor.fetchone()[0]
                        if expired_count > 0:
                            conn.execute("DELETE FROM sessions WHERE last_active < ?", (threshold,))
                            import logging
                            logging.getLogger("tripcraft").info(f"Evicted {expired_count} expired session(s) from database.")
            except Exception as e:
                import logging
                logging.getLogger("tripcraft").error(f"Session cleanup error (non-fatal): {e}")
