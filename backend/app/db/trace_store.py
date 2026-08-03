import sqlite3
import json
import os
import threading
import uuid
from datetime import datetime


class TraceStore:
    """Persists per-turn LLM call traces so devtools can inspect past turns after restart."""

    SCHEMA_VERSION = 1

    _MIGRATIONS = {
        1: [
            """CREATE TABLE IF NOT EXISTS llm_traces (
                id TEXT PRIMARY KEY,
                campaign_id TEXT NOT NULL,
                turn_index INTEGER NOT NULL,
                action TEXT NOT NULL DEFAULT '',
                entries TEXT NOT NULL DEFAULT '[]',
                call_count INTEGER NOT NULL DEFAULT 0,
                total_input_tokens INTEGER NOT NULL DEFAULT 0,
                total_output_tokens INTEGER NOT NULL DEFAULT 0,
                total_cache_read_tokens INTEGER NOT NULL DEFAULT 0,
                total_cache_creation_tokens INTEGER NOT NULL DEFAULT 0,
                total_time_s REAL NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )""",
            "CREATE INDEX IF NOT EXISTS idx_trace_campaign ON llm_traces(campaign_id, created_at)",
        ],
    }

    def __init__(self, db_path: str = "traces.db"):
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
        action: str,
        entries: list,
        summary: dict | None = None,
        keep: int | None = None,
    ) -> dict:
        summary = summary or {}
        if keep is None:
            keep = int(os.environ.get("LLM_TRACE_KEEP", "100"))

        trace_id = str(uuid.uuid4())
        created_at = datetime.utcnow().isoformat()

        with self._lock:
            row = self._conn.execute(
                "SELECT MAX(turn_index) FROM llm_traces WHERE campaign_id=?",
                (campaign_id,),
            ).fetchone()
            turn_index = (row[0] or 0) + 1

            self._conn.execute(
                "INSERT INTO llm_traces VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    trace_id,
                    campaign_id,
                    turn_index,
                    action,
                    json.dumps(entries, ensure_ascii=False),
                    len(entries),
                    summary.get("total_input_tokens", 0),
                    summary.get("total_output_tokens", 0),
                    summary.get("total_cache_read_tokens", 0),
                    summary.get("total_cache_creation_tokens", 0),
                    summary.get("total_time_s", 0),
                    created_at,
                ),
            )

            # Prune down to the `keep` most recent turns for this campaign.
            stale_rows = self._conn.execute(
                "SELECT turn_index FROM llm_traces WHERE campaign_id=? ORDER BY turn_index DESC",
                (campaign_id,),
            ).fetchall()
            stale_indices = [r[0] for r in stale_rows[keep:]]
            if stale_indices:
                placeholders = ",".join("?" for _ in stale_indices)
                self._conn.execute(
                    f"DELETE FROM llm_traces WHERE campaign_id=? AND turn_index IN ({placeholders})",
                    (campaign_id, *stale_indices),
                )

            self._conn.commit()

        return {
            "key": trace_id,
            "label": f"turn {turn_index}",
            "turn_index": turn_index,
            "action": action,
            "created_at": created_at,
            "entries": entries,
            "summary": {
                "call_count": len(entries),
                "total_input_tokens": summary.get("total_input_tokens", 0),
                "total_output_tokens": summary.get("total_output_tokens", 0),
                "total_cache_read_tokens": summary.get("total_cache_read_tokens", 0),
                "total_cache_creation_tokens": summary.get("total_cache_creation_tokens", 0),
                "total_time_s": summary.get("total_time_s", 0),
            },
        }

    def get_recent(self, campaign_id: str, limit: int = 25) -> list[dict]:
        rows = self._conn.execute(
            "SELECT id, turn_index, action, entries, call_count, total_input_tokens, "
            "total_output_tokens, total_cache_read_tokens, total_cache_creation_tokens, "
            "total_time_s, created_at FROM llm_traces WHERE campaign_id=? "
            "ORDER BY created_at DESC LIMIT ?",
            (campaign_id, limit),
        ).fetchall()
        return [self._row_to_dict(r) for r in reversed(rows)]

    def _row_to_dict(self, row) -> dict:
        (
            trace_id, turn_index, action, entries_json, call_count,
            total_input_tokens, total_output_tokens, total_cache_read_tokens,
            total_cache_creation_tokens, total_time_s, created_at,
        ) = row
        try:
            entries = json.loads(entries_json)
        except (TypeError, json.JSONDecodeError):
            entries = []
        return {
            "key": trace_id,
            "label": f"turn {turn_index}",
            "turn_index": turn_index,
            "action": action,
            "created_at": created_at,
            "entries": entries,
            "summary": {
                "call_count": call_count,
                "total_input_tokens": total_input_tokens,
                "total_output_tokens": total_output_tokens,
                "total_cache_read_tokens": total_cache_read_tokens,
                "total_cache_creation_tokens": total_cache_creation_tokens,
                "total_time_s": total_time_s,
            },
        }

    def delete_for_campaign(self, campaign_id: str) -> int:
        with self._lock:
            cursor = self._conn.execute(
                "DELETE FROM llm_traces WHERE campaign_id=?", (campaign_id,)
            )
            self._conn.commit()
            return cursor.rowcount

    def list_campaigns(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT campaign_id, COUNT(*), MAX(created_at) FROM llm_traces "
            "GROUP BY campaign_id ORDER BY MAX(created_at) DESC"
        ).fetchall()
        return [
            {"campaign_id": r[0], "turns": r[1], "last_created_at": r[2]}
            for r in rows
        ]

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    def close(self):
        self._conn.close()
