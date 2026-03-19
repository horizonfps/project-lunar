import os
from datetime import datetime
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.db.scenario_store import ScenarioStore, StoryCardType
from app.db.event_store import EventStore

router = APIRouter()


_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def _get_store() -> ScenarioStore:
    db_path = os.environ.get("SCENARIO_DB_PATH", os.path.join(_BACKEND_DIR, "scenarios.db"))
    return ScenarioStore(db_path)


def _get_event_store() -> EventStore:
    db_path = os.environ.get("EVENT_DB_PATH", os.path.join(_BACKEND_DIR, "events.db"))
    return EventStore(db_path)


class CreateScenarioRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    tone_instructions: str = Field(default="", max_length=5000)
    opening_narrative: str = Field(default="", max_length=10000)
    language: str = Field(default="en", max_length=10)
    lore_text: str = Field(default="", max_length=50000)


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


@router.post("/", status_code=201)
def create_scenario(req: CreateScenarioRequest):
    with _get_store() as store:
        scenario = store.create_scenario(
            title=req.title,
            description=req.description,
            tone_instructions=req.tone_instructions,
            opening_narrative=req.opening_narrative,
            language=req.language,
            lore_text=req.lore_text,
        )
    return scenario.__dict__


@router.get("/")
def list_scenarios():
    with _get_store() as store:
        return [s.__dict__ for s in store.list_scenarios()]


@router.post("/import", status_code=201)
def import_scenario(req: ImportScenarioRequest):
    with _get_store() as store:
        scenario = store.create_scenario(
            title=req.scenario.title,
            description=req.scenario.description,
            tone_instructions=req.scenario.tone_instructions,
            opening_narrative=req.scenario.opening_narrative,
            language=req.scenario.language,
            lore_text=req.scenario.lore_text,
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
        },
        "story_cards": [
            {"card_type": c.card_type.value, "name": c.name, "content": c.content}
            for c in story_cards
        ],
        "campaigns": [
            {"player_name": c.player_name}
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
