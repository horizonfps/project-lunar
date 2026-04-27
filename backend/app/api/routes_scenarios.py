import logging
import os
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.db.scenario_store import ScenarioStore, StoryCardType
from app.db.event_store import EventStore
from app.engines.llm_router import LLMRouter, LLMConfig
from app.engines.opening_generator import (
    format_setup_lines,
    generate_opening,
    synthesize_sample_answers,
)

logger = logging.getLogger(__name__)

router = APIRouter()


_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def _get_store() -> ScenarioStore:
    db_path = os.environ.get("SCENARIO_DB_PATH", os.path.join(_BACKEND_DIR, "scenarios.db"))
    return ScenarioStore(db_path)


def _get_event_store() -> EventStore:
    db_path = os.environ.get("EVENT_DB_PATH", os.path.join(_BACKEND_DIR, "events.db"))
    return EventStore(db_path)


class SetupOption(BaseModel):
    label: str = Field(..., max_length=200)
    description: str = Field(default="", max_length=4000)


class SetupQuestion(BaseModel):
    id: str = Field(..., min_length=1, max_length=64)
    var_name: str = Field(..., min_length=1, max_length=64)
    prompt: str = Field(..., min_length=1, max_length=4000)
    type: str = Field(..., pattern=r"^(text|choice)$")
    options: list[SetupOption] = []
    allow_custom: bool = False
    required: bool = True


class CreateScenarioRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    tone_instructions: str = Field(default="", max_length=50000)
    opening_narrative: str = Field(default="", max_length=50000)
    language: str = Field(default="en", max_length=10)
    lore_text: str = Field(default="", max_length=50000)
    setup_questions: list[SetupQuestion] = []
    opening_mode: Literal["fixed", "ai"] = "fixed"
    ai_opening_directive: str = Field(default="", max_length=4000)


class PreviewOpeningRequest(BaseModel):
    language: str = Field(default="en", max_length=10)
    tone: str = Field(default="", max_length=50000)
    lore: str = Field(default="", max_length=50000)
    directive: str = Field(default="", max_length=4000)
    setup_questions: list[SetupQuestion] = []
    sample_answers: dict = Field(default_factory=dict)


class AddStoryCardRequest(BaseModel):
    card_type: StoryCardType
    name: str = Field(..., min_length=1, max_length=200)
    content: dict = {}


class CampaignData(BaseModel):
    player_name: str


class ImportScenarioRequest(BaseModel):
    version: str
    scenario: CreateScenarioRequest
    story_cards: list[AddStoryCardRequest] = []
    campaigns: list[CampaignData] = []


def _validate_unique_var_names(questions: list[SetupQuestion]) -> None:
    seen: set[str] = set()
    for q in questions:
        if q.var_name in seen:
            raise HTTPException(status_code=400, detail=f"Duplicate var_name: {q.var_name}")
        seen.add(q.var_name)


@router.post("/", status_code=201)
def create_scenario(req: CreateScenarioRequest):
    _validate_unique_var_names(req.setup_questions)
    with _get_store() as store:
        scenario = store.create_scenario(
            title=req.title,
            description=req.description,
            tone_instructions=req.tone_instructions,
            opening_narrative=req.opening_narrative,
            language=req.language,
            lore_text=req.lore_text,
            setup_questions=[q.model_dump() for q in req.setup_questions],
            opening_mode=req.opening_mode,
            ai_opening_directive=req.ai_opening_directive,
        )
    return scenario.__dict__


@router.post("/preview-opening")
async def preview_opening(req: PreviewOpeningRequest):
    """Render a sample AI opening for the scenario builder.

    Uses ``sample_answers`` if supplied, otherwise synthesizes them from the
    scenario's setup questions so authors get a usable preview without having
    to fill in mock data by hand.
    """
    questions = [q.model_dump() for q in req.setup_questions]
    answers = req.sample_answers or synthesize_sample_answers(questions)
    lines = format_setup_lines(answers, questions)
    router_ = LLMRouter(LLMConfig())
    text = await generate_opening(
        language=req.language,
        tone=req.tone,
        lore=req.lore,
        character_setup_lines=lines,
        director_note=req.directive,
        router=router_,
    )
    return {"opening": text, "sample_answers": answers}


@router.get("/")
def list_scenarios():
    with _get_store() as store:
        return [s.__dict__ for s in store.list_scenarios()]


@router.post("/import", status_code=201)
def import_scenario(req: ImportScenarioRequest):
    _validate_unique_var_names(req.scenario.setup_questions)
    with _get_store() as store:
        scenario = store.create_scenario(
            title=req.scenario.title,
            description=req.scenario.description,
            tone_instructions=req.scenario.tone_instructions,
            opening_narrative=req.scenario.opening_narrative,
            language=req.scenario.language,
            lore_text=req.scenario.lore_text,
            setup_questions=[q.model_dump() for q in req.scenario.setup_questions],
            opening_mode=req.scenario.opening_mode,
            ai_opening_directive=req.scenario.ai_opening_directive,
        )
        for card in req.story_cards:
            store.add_story_card(scenario.id, card.card_type, card.name, card.content)
        for campaign in req.campaigns:
            store.create_campaign(scenario.id, campaign.player_name)
    return scenario.__dict__


@router.get("/{scenario_id}")
def get_scenario(scenario_id: str):
    with _get_store() as store:
        scenario = store.get_scenario(scenario_id)
    if not scenario:
        raise HTTPException(status_code=404, detail="Scenario not found")
    return scenario.__dict__


@router.post("/{scenario_id}/story-cards", status_code=201)
def add_story_card(scenario_id: str, req: AddStoryCardRequest):
    with _get_store() as store:
        card = store.add_story_card(scenario_id, req.card_type, req.name, req.content)
    return card.__dict__


@router.get("/{scenario_id}/story-cards")
def get_story_cards(scenario_id: str):
    with _get_store() as store:
        return [c.__dict__ for c in store.get_story_cards(scenario_id)]


@router.post("/{scenario_id}/campaigns", status_code=201)
def create_campaign(scenario_id: str, req: CampaignData):
    with _get_store() as store:
        scenario = store.get_scenario(scenario_id)
        if not scenario:
            raise HTTPException(status_code=404, detail="Scenario not found")
        campaign = store.create_campaign(scenario_id, req.player_name)
    return campaign.__dict__


@router.get("/{scenario_id}/campaigns")
def get_campaigns(scenario_id: str):
    with _get_store() as store:
        scenario = store.get_scenario(scenario_id)
        campaigns = store.get_campaigns(scenario_id) if scenario else None
    if scenario is None:
        raise HTTPException(status_code=404, detail="Scenario not found")
    return [c.__dict__ for c in campaigns]


@router.get("/{scenario_id}/export")
def export_scenario(scenario_id: str):
    with _get_store() as store:
        scenario = store.get_scenario(scenario_id)
        story_cards = store.get_story_cards(scenario_id) if scenario else []
        campaigns = store.get_campaigns(scenario_id) if scenario else []
    if not scenario:
        raise HTTPException(status_code=404, detail="Scenario not found")

    return {
        "version": "1.0",
        "exported_at": datetime.utcnow().isoformat(),
        "scenario": {
            "title": scenario.title,
            "description": scenario.description,
            "tone_instructions": scenario.tone_instructions,
            "opening_narrative": scenario.opening_narrative,
            "language": scenario.language,
            "lore_text": scenario.lore_text,
            "setup_questions": scenario.setup_questions,
            "opening_mode": scenario.opening_mode,
            "ai_opening_directive": scenario.ai_opening_directive,
        },
        "story_cards": [
            {"card_type": c.card_type.value, "name": c.name, "content": c.content}
            for c in story_cards
        ],
        "campaigns": [
            {"player_name": c.player_name, "setup_answers": c.setup_answers}
            for c in campaigns
        ],
    }


@router.delete("/{scenario_id}/campaigns/{campaign_id}", status_code=200)
def delete_campaign(scenario_id: str, campaign_id: str):
    with _get_store() as store:
        deleted = store.delete_campaign(campaign_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Campaign not found")
    event_store = _get_event_store()
    try:
        event_store.delete_by_campaign(campaign_id)
    finally:
        event_store.close()
    return {"status": "ok"}


@router.delete("/{scenario_id}", status_code=200)
def delete_scenario(scenario_id: str):
    with _get_store() as store:
        # Get all campaigns to clean up their events
        campaigns = store.get_campaigns(scenario_id)
        deleted = store.delete_scenario(scenario_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Scenario not found")
    event_store = _get_event_store()
    try:
        for c in campaigns:
            event_store.delete_by_campaign(c.id)
    finally:
        event_store.close()
    return {"status": "ok"}
