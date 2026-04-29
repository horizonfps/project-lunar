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
    POWER_LEVEL_UPDATE = "POWER_LEVEL_UPDATE"
    AI_OPENING_GENERATED = "AI_OPENING_GENERATED"


_EventBase = namedtuple(
    "Event",
    [
        "id", "campaign_id", "event_type", "payload",
        "narrative_time_delta", "location", "entities",
        "created_at", "witnessed_by",
    ],
)


class Event(_EventBase):
    """Immutable event record backed by a namedtuple. All mutation raises AttributeError.

    `witnessed_by` is a list of NPC names physically present in the scene this
    event represents (Camada 3 — perspective filter). Empty list means either
    "no NPCs present" or "witness extraction has not run yet". Player presence
    is implicit and never recorded here.
    """

    __slots__ = ()

    def __setattr__(self, name, value):
        raise AttributeError("Event is immutable")

    def __delattr__(self, name):
        raise AttributeError("Event is immutable")


class EventStore:
    SCHEMA_VERSION = 2

    # Each migration is a list of SQL statements to run for that version.
    # Key = target version, value = list of SQL to apply.
    _MIGRATIONS = {
        1: [
            """CREATE TABLE IF NOT EXISTS events (
                id TEXT PRIMARY KEY,
                campaign_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                payload TEXT NOT NULL,
                narrative_time_delta INTEGER NOT NULL DEFAULT 0,
                location TEXT NOT NULL DEFAULT '',
                entities TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL
            )""",
            "CREATE INDEX IF NOT EXISTS idx_campaign ON events(campaign_id, created_at)",
        ],
        2: [
            "ALTER TABLE events ADD COLUMN witnessed_by TEXT NOT NULL DEFAULT '[]'",
        ],
    }

    def __init__(self, db_path: str = "events.db"):
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._lock = threading.Lock()
        self._migrate()

    def _get_schema_version(self) -> int:
        try:
            row = self._conn.execute(
                "SELECT version FROM schema_version ORDER BY version DESC LIMIT 1"
            ).fetchone()
            return row[0] if row else 0
        except sqlite3.OperationalError:
            return 0

    def _migrate(self):
        with self._lock:
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
            )
            current = self._get_schema_version()
            for version in sorted(self._MIGRATIONS.keys()):
                if version <= current:
                    continue
                for sql in self._MIGRATIONS[version]:
                    self._conn.execute(sql)
                self._conn.execute(
                    "INSERT INTO schema_version VALUES (?, ?)",
                    (version, datetime.utcnow().isoformat()),
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
        witnessed_by: list[str] | None = None,
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
            witnessed_by=list(witnessed_by or []),
        )
        with self._lock:
            self._conn.execute(
                "INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    event.id,
                    event.campaign_id,
                    event.event_type.value,
                    json.dumps(event.payload),
                    event.narrative_time_delta,
                    event.location,
                    json.dumps(event.entities),
                    event.created_at,
                    json.dumps(event.witnessed_by),
                ),
            )
            self._conn.commit()
        return event

    def update_witnessed_by(self, event_id: str, witnessed_by: list[str]) -> bool:
        """Update the witnessed_by list for an existing event.

        Used by the perspective-filter pipeline (Camada 3): the witness LLM
        call runs after the narrator response is persisted, then writes back
        the extracted NPC list onto the just-appended event.
        """
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE events SET witnessed_by=? WHERE id=?",
                (json.dumps(list(witnessed_by or [])), event_id),
            )
            self._conn.commit()
            return cursor.rowcount > 0

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
        # witnessed_by is the 9th column (index 8). Older rows that predate
        # migration 2 will have it filled with the default '[]' by the
        # ALTER TABLE statement, so this is always safe to parse.
        try:
            witnessed_by = json.loads(row[8]) if len(row) > 8 and row[8] else []
        except (TypeError, json.JSONDecodeError):
            witnessed_by = []
        return Event(
            id=row[0],
            campaign_id=row[1],
            event_type=EventType(row[2]),
            payload=json.loads(row[3]),
            narrative_time_delta=row[4],
            location=row[5],
            entities=json.loads(row[6]),
            created_at=row[7],
            witnessed_by=witnessed_by,
        )

    def delete_last_pair(self, campaign_id: str) -> int:
        """Delete the last PLAYER_ACTION and all events created after it.

        Returns the number of deleted rows.
        """
        with self._lock:
            # Find the last PLAYER_ACTION event for this campaign
            row = self._conn.execute(
                "SELECT created_at FROM events WHERE campaign_id=? AND event_type=? ORDER BY created_at DESC LIMIT 1",
                (campaign_id, EventType.PLAYER_ACTION.value),
            ).fetchone()
            if not row:
                return 0
            last_action_time = row[0]
            # Delete the last PLAYER_ACTION and everything after it
            cursor = self._conn.execute(
                "DELETE FROM events WHERE campaign_id=? AND created_at >= ?",
                (campaign_id, last_action_time),
            )
            self._conn.commit()
            return cursor.rowcount

    def delete_npc_thoughts(self, campaign_id: str, npc_name: str) -> int:
        """Delete all NPC_THOUGHT events for a specific NPC name."""
        with self._lock:
            cursor = self._conn.execute(
                "DELETE FROM events WHERE campaign_id=? AND event_type=? AND json_extract(payload, '$.name')=?",
                (campaign_id, EventType.NPC_THOUGHT.value, npc_name),
            )
            self._conn.commit()
            return cursor.rowcount

    def upsert_npc_thought(self, campaign_id: str, npc_name: str, thoughts: dict, aliases: list[str] | None = None) -> None:
        """Replace the latest NPC_THOUGHT event for an NPC with updated data."""
        self.delete_npc_thoughts(campaign_id, npc_name)
        self.append(
            campaign_id=campaign_id,
            event_type=EventType.NPC_THOUGHT,
            payload={"name": npc_name, "thoughts": thoughts, "aliases": aliases or []},
            narrative_time_delta=0,
            location="",
            entities=[],
        )

    def delete_by_campaign(self, campaign_id: str) -> int:
        """Delete all events for a campaign. Returns the number of deleted rows."""
        with self._lock:
            cursor = self._conn.execute(
                "DELETE FROM events WHERE campaign_id=?", (campaign_id,)
            )
            self._conn.commit()
            return cursor.rowcount

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    def close(self):
        self._conn.close()
