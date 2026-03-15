import sqlite3
import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from threading import Lock


class StoryCardType(str, Enum):
    NPC = "NPC"
    LOCATION = "LOCATION"
    FACTION = "FACTION"
    ITEM = "ITEM"
    LORE = "LORE"


@dataclass
class Scenario:
    id: str
    title: str
    description: str
    tone_instructions: str
    opening_narrative: str
    language: str
    lore_text: str
    created_at: str


@dataclass
class StoryCard:
    id: str
    scenario_id: str
    card_type: StoryCardType
    name: str
    content: dict
    created_at: str


@dataclass
class Campaign:
    id: str
    scenario_id: str
    player_name: str
    created_at: str


class ScenarioStore:
    SCHEMA_VERSION = 1

    _MIGRATIONS = {
        1: [
            """CREATE TABLE IF NOT EXISTS scenarios (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                tone_instructions TEXT NOT NULL DEFAULT '',
                opening_narrative TEXT NOT NULL DEFAULT '',
                language TEXT NOT NULL DEFAULT 'en',
                lore_text TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS story_cards (
                id TEXT PRIMARY KEY,
                scenario_id TEXT NOT NULL REFERENCES scenarios(id),
                card_type TEXT NOT NULL,
                name TEXT NOT NULL,
                content TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS campaigns (
                id TEXT PRIMARY KEY,
                scenario_id TEXT NOT NULL REFERENCES scenarios(id),
                player_name TEXT NOT NULL,
                created_at TEXT NOT NULL
            )""",
        ],
        # Future migrations go here:
        # 2: ["ALTER TABLE scenarios ADD COLUMN ..."],
    }

    def __init__(self, db_path: str = "scenarios.db"):
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._lock = Lock()
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

    def create_scenario(
        self,
        title: str,
        description: str = "",
        tone_instructions: str = "",
        opening_narrative: str = "",
        language: str = "en",
        lore_text: str = "",
    ) -> Scenario:
        scenario = Scenario(
            id=str(uuid.uuid4()),
            title=title,
            description=description,
            tone_instructions=tone_instructions,
            opening_narrative=opening_narrative,
            language=language,
            lore_text=lore_text,
            created_at=datetime.utcnow().isoformat(),
        )
        with self._lock:
            self._conn.execute(
                "INSERT INTO scenarios VALUES (?,?,?,?,?,?,?,?)",
                (scenario.id, scenario.title, scenario.description,
                 scenario.tone_instructions, scenario.opening_narrative,
                 scenario.language, scenario.lore_text, scenario.created_at),
            )
            self._conn.commit()
        return scenario

    def get_scenario(self, scenario_id: str) -> "Scenario | None":
        row = self._conn.execute(
            "SELECT * FROM scenarios WHERE id=?", (scenario_id,)
        ).fetchone()
        if not row:
            return None
        return Scenario(*row)

    def list_scenarios(self) -> "list[Scenario]":
        rows = self._conn.execute(
            "SELECT * FROM scenarios ORDER BY created_at DESC"
        ).fetchall()
        return [Scenario(*r) for r in rows]

    def add_story_card(
        self,
        scenario_id: str,
        card_type: StoryCardType,
        name: str,
        content: dict,
    ) -> StoryCard:
        card = StoryCard(
            id=str(uuid.uuid4()),
            scenario_id=scenario_id,
            card_type=card_type,
            name=name,
            content=content,
            created_at=datetime.utcnow().isoformat(),
        )
        with self._lock:
            self._conn.execute(
                "INSERT INTO story_cards VALUES (?,?,?,?,?,?)",
                (card.id, card.scenario_id, card.card_type.value,
                 card.name, json.dumps(card.content), card.created_at),
            )
            self._conn.commit()
        return card

    def get_story_cards(self, scenario_id: str) -> "list[StoryCard]":
        rows = self._conn.execute(
            "SELECT * FROM story_cards WHERE scenario_id=? ORDER BY created_at ASC",
            (scenario_id,),
        ).fetchall()
        return [
            StoryCard(r[0], r[1], StoryCardType(r[2]), r[3], json.loads(r[4]), r[5])
            for r in rows
        ]

    def create_campaign(self, scenario_id: str, player_name: str) -> Campaign:
        campaign = Campaign(
            id=str(uuid.uuid4()),
            scenario_id=scenario_id,
            player_name=player_name,
            created_at=datetime.utcnow().isoformat(),
        )
        with self._lock:
            self._conn.execute(
                "INSERT INTO campaigns VALUES (?,?,?,?)",
                (campaign.id, campaign.scenario_id, campaign.player_name, campaign.created_at),
            )
            self._conn.commit()
        return campaign

    def get_campaigns(self, scenario_id: str) -> "list[Campaign]":
        rows = self._conn.execute(
            "SELECT * FROM campaigns WHERE scenario_id=? ORDER BY created_at DESC",
            (scenario_id,),
        ).fetchall()
        return [Campaign(*r) for r in rows]

    def close(self):
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False
