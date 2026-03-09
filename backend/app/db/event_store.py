import sqlite3
import json
import threading
import uuid
from collections import namedtuple
from datetime import datetime
from enum import Enum


class EventType(str, Enum):
    PLAYER_ACTION = "PLAYER_ACTION"
    NARRATOR_RESPONSE = "NARRATOR_RESPONSE"
    WORLD_TICK = "WORLD_TICK"
    COMBAT_ACTION = "COMBAT_ACTION"
    COMBAT_RESULT = "COMBAT_RESULT"
    PLOT_GENERATION = "PLOT_GENERATION"
    NPC_THOUGHT = "NPC_THOUGHT"
    JOURNAL_ENTRY = "JOURNAL_ENTRY"
    MEMORY_CRYSTAL = "MEMORY_CRYSTAL"
    TIMESKIP = "TIMESKIP"
    INVENTORY = "INVENTORY"


_EventBase = namedtuple(
    "Event",
    ["id", "campaign_id", "event_type", "payload", "narrative_time_delta", "location", "entities", "created_at"],
)


class Event(_EventBase):
    """Immutable event record backed by a namedtuple. All mutation raises AttributeError."""

    __slots__ = ()

    def __setattr__(self, name, value):
        raise AttributeError("Event is immutable")

    def __delattr__(self, name):
        raise AttributeError("Event is immutable")


class EventStore:
    def __init__(self, db_path: str = "events.db"):
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._lock = threading.Lock()
        self._create_table()

    def _create_table(self):
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id TEXT PRIMARY KEY,
                campaign_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                payload TEXT NOT NULL,
                narrative_time_delta INTEGER NOT NULL DEFAULT 0,
                location TEXT NOT NULL DEFAULT '',
                entities TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL
            )
        """)
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_campaign ON events(campaign_id, created_at)"
        )
        self._conn.commit()

    def append(
        self,
        campaign_id: str,
        event_type: EventType,
        payload: dict,
        narrative_time_delta: int,
        location: str,
        entities: list,
    ) -> Event:
        event = Event(
            id=str(uuid.uuid4()),
            campaign_id=campaign_id,
            event_type=event_type,
            payload=payload,
            narrative_time_delta=narrative_time_delta,
            location=location,
            entities=entities,
            created_at=datetime.utcnow().isoformat(),
        )
        with self._lock:
            self._conn.execute(
                "INSERT INTO events VALUES (?,?,?,?,?,?,?,?)",
                (
                    event.id,
                    event.campaign_id,
                    event.event_type.value,
                    json.dumps(event.payload),
                    event.narrative_time_delta,
                    event.location,
                    json.dumps(event.entities),
                    event.created_at,
                ),
            )
            self._conn.commit()
        return event

    def get_recent(self, campaign_id: str, limit: int = 20) -> list:
        rows = self._conn.execute(
            "SELECT * FROM events WHERE campaign_id=? ORDER BY created_at DESC LIMIT ?",
            (campaign_id, limit),
        ).fetchall()
        return [self._row_to_event(r) for r in reversed(rows)]

    def get_by_type(self, campaign_id: str, event_type: EventType, limit: int = 500) -> list:
        rows = self._conn.execute(
            """
            SELECT * FROM events
            WHERE campaign_id=? AND event_type=?
            ORDER BY created_at ASC
            LIMIT ?
            """,
            (campaign_id, event_type.value, limit),
        ).fetchall()
        return [self._row_to_event(r) for r in rows]

    def get_after(
        self,
        campaign_id: str,
        after_created_at: str | None = None,
        limit: int = 100,
        event_types: list[EventType] | None = None,
    ) -> list:
        query = "SELECT * FROM events WHERE campaign_id=?"
        params: list = [campaign_id]

        if after_created_at:
            query += " AND created_at > ?"
            params.append(after_created_at)

        if event_types:
            placeholders = ",".join("?" for _ in event_types)
            query += f" AND event_type IN ({placeholders})"
            params.extend(et.value for et in event_types)

        query += " ORDER BY created_at ASC LIMIT ?"
        params.append(limit)

        rows = self._conn.execute(query, tuple(params)).fetchall()
        return [self._row_to_event(r) for r in rows]

    def get_total_narrative_time(self, campaign_id: str) -> int:
        row = self._conn.execute(
            "SELECT SUM(narrative_time_delta) FROM events WHERE campaign_id=?",
            (campaign_id,),
        ).fetchone()
        return row[0] or 0

    def _row_to_event(self, row) -> Event:
        return Event(
            id=row[0],
            campaign_id=row[1],
            event_type=EventType(row[2]),
            payload=json.loads(row[3]),
            narrative_time_delta=row[4],
            location=row[5],
            entities=json.loads(row[6]),
            created_at=row[7],
        )

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    def close(self):
        self._conn.close()
