import sqlite3
import json
import uuid
from dataclasses import dataclass, field
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
    setup_questions: list = field(default_factory=list)
    opening_mode: str = "fixed"  # "fixed" | "ai"
    ai_opening_directive: str = ""


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
    setup_answers: dict = field(default_factory=dict)
    generated_opening: str = ""


class ScenarioStore:
    SCHEMA_VERSION = 3

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
        2: [
            "ALTER TABLE scenarios ADD COLUMN setup_questions TEXT NOT NULL DEFAULT '[]'",
            "ALTER TABLE campaigns ADD COLUMN setup_answers TEXT NOT NULL DEFAULT '{}'",
        ],
        3: [
            "ALTER TABLE scenarios ADD COLUMN opening_mode TEXT NOT NULL DEFAULT 'fixed'",
            "ALTER TABLE scenarios ADD COLUMN ai_opening_directive TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE campaigns ADD COLUMN generated_opening TEXT NOT NULL DEFAULT ''",
        ],
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

    _SCENARIO_COLS = (
        "id, title, description, tone_instructions, opening_narrative, "
        "language, lore_text, created_at, setup_questions, "
        "opening_mode, ai_opening_directive"
    )

    def create_scenario(
        self,
        title: str,
        description: str = "",
        tone_instructions: str = "",
        opening_narrative: str = "",
        language: str = "en",
        lore_text: str = "",
        setup_questions: list | None = None,
        opening_mode: str = "fixed",
        ai_opening_directive: str = "",
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
            setup_questions=setup_questions or [],
            opening_mode=opening_mode if opening_mode in ("fixed", "ai") else "fixed",
            ai_opening_directive=ai_opening_directive,
        )
        with self._lock:
            self._conn.execute(
                f"INSERT INTO scenarios ({self._SCENARIO_COLS}) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (scenario.id, scenario.title, scenario.description,
                 scenario.tone_instructions, scenario.opening_narrative,
                 scenario.language, scenario.lore_text, scenario.created_at,
                 json.dumps(scenario.setup_questions),
                 scenario.opening_mode, scenario.ai_opening_directive),
            )
            self._conn.commit()
        return scenario

    @staticmethod
    def _row_to_scenario(row) -> Scenario:
        # Columns (in order matching _SCENARIO_COLS):
        #   id, title, description, tone_instructions, opening_narrative,
        #   language, lore_text, created_at, setup_questions(JSON),
        #   opening_mode, ai_opening_directive
        try:
            setup_questions = json.loads(row[8]) if row[8] else []
        except (json.JSONDecodeError, TypeError):
            setup_questions = []
        opening_mode = row[9] if len(row) > 9 and row[9] else "fixed"
        ai_directive = row[10] if len(row) > 10 and row[10] is not None else ""
        return Scenario(
            id=row[0], title=row[1], description=row[2],
            tone_instructions=row[3], opening_narrative=row[4],
            language=row[5], lore_text=row[6], created_at=row[7],
            setup_questions=setup_questions,
            opening_mode=opening_mode,
            ai_opening_directive=ai_directive,
        )

    def get_scenario(self, scenario_id: str) -> "Scenario | None":
        row = self._conn.execute(
            f"SELECT {self._SCENARIO_COLS} FROM scenarios WHERE id=?", (scenario_id,)
        ).fetchone()
        if not row:
            return None
        return self._row_to_scenario(row)

    def list_scenarios(self) -> "list[Scenario]":
        rows = self._conn.execute(
            f"SELECT {self._SCENARIO_COLS} FROM scenarios ORDER BY created_at DESC"
        ).fetchall()
        return [self._row_to_scenario(r) for r in rows]

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

    _CAMPAIGN_COLS = (
        "id, scenario_id, player_name, created_at, setup_answers, generated_opening"
    )

    def create_campaign(self, scenario_id: str, player_name: str) -> Campaign:
        campaign = Campaign(
            id=str(uuid.uuid4()),
            scenario_id=scenario_id,
            player_name=player_name,
            created_at=datetime.utcnow().isoformat(),
            setup_answers={},
            generated_opening="",
        )
        with self._lock:
            self._conn.execute(
                f"INSERT INTO campaigns ({self._CAMPAIGN_COLS}) "
                "VALUES (?,?,?,?,?,?)",
                (campaign.id, campaign.scenario_id, campaign.player_name,
                 campaign.created_at, json.dumps(campaign.setup_answers),
                 campaign.generated_opening),
            )
            self._conn.commit()
        return campaign

    @staticmethod
    def _row_to_campaign(row) -> Campaign:
        # Columns (matching _CAMPAIGN_COLS):
        #   id, scenario_id, player_name, created_at, setup_answers(JSON),
        #   generated_opening
        try:
            setup_answers = json.loads(row[4]) if row[4] else {}
        except (json.JSONDecodeError, TypeError):
            setup_answers = {}
        generated_opening = row[5] if len(row) > 5 and row[5] is not None else ""
        return Campaign(
            id=row[0], scenario_id=row[1], player_name=row[2],
            created_at=row[3], setup_answers=setup_answers,
            generated_opening=generated_opening,
        )

    def get_campaign(self, campaign_id: str) -> "Campaign | None":
        row = self._conn.execute(
            f"SELECT {self._CAMPAIGN_COLS} FROM campaigns WHERE id=?",
            (campaign_id,),
        ).fetchone()
        if not row:
            return None
        return self._row_to_campaign(row)

    def get_campaigns(self, scenario_id: str) -> "list[Campaign]":
        rows = self._conn.execute(
            f"SELECT {self._CAMPAIGN_COLS} FROM campaigns "
            "WHERE scenario_id=? ORDER BY created_at DESC",
            (scenario_id,),
        ).fetchall()
        return [self._row_to_campaign(r) for r in rows]

    def update_setup_answers(self, campaign_id: str, answers: dict) -> bool:
        """Persist setup wizard answers for a campaign."""
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE campaigns SET setup_answers=? WHERE id=?",
                (json.dumps(answers), campaign_id),
            )
            self._conn.commit()
            return cursor.rowcount > 0

    def update_generated_opening(self, campaign_id: str, text: str) -> bool:
        """Persist an AI-generated opening for the campaign."""
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE campaigns SET generated_opening=? WHERE id=?",
                (text or "", campaign_id),
            )
            self._conn.commit()
            return cursor.rowcount > 0

    def delete_campaign(self, campaign_id: str) -> bool:
        """Delete a campaign by id. Returns True if a row was deleted."""
        with self._lock:
            cursor = self._conn.execute(
                "DELETE FROM campaigns WHERE id=?", (campaign_id,)
            )
            self._conn.commit()
            return cursor.rowcount > 0

    def delete_scenario(self, scenario_id: str) -> bool:
        """Delete a scenario and all its story cards and campaigns."""
        with self._lock:
            self._conn.execute(
                "DELETE FROM story_cards WHERE scenario_id=?", (scenario_id,)
            )
            self._conn.execute(
                "DELETE FROM campaigns WHERE scenario_id=?", (scenario_id,)
            )
            cursor = self._conn.execute(
                "DELETE FROM scenarios WHERE id=?", (scenario_id,)
            )
            self._conn.commit()
            return cursor.rowcount > 0

    def close(self):
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False
