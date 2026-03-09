import json
import pytest

from app.engines.npc_mind_engine import NpcMindEngine, NpcMind


class FakeLLM:
    def __init__(self, response: str = ""):
        self._response = response

    async def complete(self, messages, **kwargs):
        return self._response


@pytest.mark.asyncio
async def test_update_npc_thoughts_parses_json():
    response = json.dumps({
        "npcs": [
            {
                "name": "Eldric",
                "thoughts": {
                    "feeling": "Suspicious of the newcomer",
                    "goal": "Protect the village",
                    "opinion_of_player": "Cautiously neutral",
                    "secret_plan": "Has hidden the artifact",
                },
            }
        ]
    })
    engine = NpcMindEngine(llm=FakeLLM(response))
    updated = await engine.update_npc_thoughts(
        campaign_id="c1",
        narrative_text="The player met Eldric at the gate.",
        world_context="A medieval village.",
    )
    assert len(updated) == 1
    assert updated[0].name == "Eldric"
    assert updated[0].get_thought("feeling") == "Suspicious of the newcomer"
    assert updated[0].get_thought("secret_plan") == "Has hidden the artifact"


@pytest.mark.asyncio
async def test_get_mind_returns_none_for_unknown():
    engine = NpcMindEngine(llm=FakeLLM())
    assert engine.get_mind("c1", "nobody") is None


@pytest.mark.asyncio
async def test_get_all_minds():
    response = json.dumps({
        "npcs": [
            {"name": "Alice", "thoughts": {"feeling": "happy"}},
            {"name": "Bob", "thoughts": {"feeling": "angry"}},
        ]
    })
    engine = NpcMindEngine(llm=FakeLLM(response))
    await engine.update_npc_thoughts("c1", "narrative", "context")
    minds = engine.get_all_minds("c1")
    assert len(minds) == 2
    names = {m.name for m in minds}
    assert "Alice" in names
    assert "Bob" in names


@pytest.mark.asyncio
async def test_update_overwrites_existing_thoughts():
    engine = NpcMindEngine(llm=FakeLLM())
    # First update
    engine._llm = FakeLLM(json.dumps({
        "npcs": [{"name": "Kira", "thoughts": {"feeling": "calm"}}]
    }))
    await engine.update_npc_thoughts("c1", "text", "ctx")
    assert engine.get_mind("c1", "kira").get_thought("feeling") == "calm"

    # Second update overwrites
    engine._llm = FakeLLM(json.dumps({
        "npcs": [{"name": "Kira", "thoughts": {"feeling": "angry", "goal": "escape"}}]
    }))
    await engine.update_npc_thoughts("c1", "text2", "ctx2")
    mind = engine.get_mind("c1", "kira")
    assert mind.get_thought("feeling") == "angry"
    assert mind.get_thought("goal") == "escape"


@pytest.mark.asyncio
async def test_handles_invalid_json():
    engine = NpcMindEngine(llm=FakeLLM("not valid json"))
    updated = await engine.update_npc_thoughts("c1", "text", "ctx")
    assert updated == []


@pytest.mark.asyncio
async def test_parses_fenced_json():
    engine = NpcMindEngine(
        llm=FakeLLM(
            '```json\n{"npcs":[{"name":"Guard","thoughts":{"feeling":"tense","goal":"hold the line"}}]}\n```'
        )
    )
    updated = await engine.update_npc_thoughts("c1", "text", "ctx")
    assert len(updated) == 1
    assert updated[0].name == "Guard"
    assert updated[0].get_thought("goal") == "hold the line"


def test_npc_mind_to_dict():
    mind = NpcMind(name="Test", campaign_id="c1")
    mind.set_thought("feeling", "happy")
    d = mind.to_dict()
    assert d["name"] == "Test"
    assert d["aliases"] == []
    assert d["thoughts"]["feeling"]["value"] == "happy"
    assert "updated_at" in d["thoughts"]["feeling"]


@pytest.mark.asyncio
async def test_dedup_merges_similar_names():
    """Fuzzy-matched names confirmed by LLM should be merged into canonical entry."""
    call_count = 0

    class DeduplicatingLLM:
        async def complete(self, messages, **kwargs):
            nonlocal call_count
            call_count += 1
            content = messages[-1]["content"] if messages else ""
            # NPC extraction call
            if "world context" in content.lower() or "narrative" in content.lower():
                return json.dumps({
                    "npcs": [{"name": "Capt Blacktide", "thoughts": {"feeling": "angry"}}]
                })
            # Dedup confirmation call
            if "same character" in messages[0]["content"].lower():
                return "YES"
            return "{}"

    engine = NpcMindEngine(llm=DeduplicatingLLM())
    engine._ensure_mind("c1", "Captain Blacktide")
    engine._minds["c1"]["captain blacktide"].set_thought("goal", "sail the seas")

    await engine.update_npc_thoughts("c1", "Capt Blacktide scowled", "world context")

    minds = engine.get_all_minds("c1")
    assert len(minds) == 1
    mind = minds[0]
    assert mind.name == "Captain Blacktide"  # longer name kept
    assert mind.get_thought("goal") == "sail the seas"
    assert mind.get_thought("feeling") == "angry"


@pytest.mark.asyncio
async def test_dedup_no_merge_when_llm_says_no():
    class NoMergeLLM:
        async def complete(self, messages, **kwargs):
            content = messages[-1]["content"] if messages else ""
            if "world context" in content.lower() or "narrative" in content.lower():
                return json.dumps({
                    "npcs": [{"name": "Blackthorn", "thoughts": {"feeling": "calm"}}]
                })
            if "same character" in messages[0]["content"].lower():
                return "NO"
            return "{}"

    engine = NpcMindEngine(llm=NoMergeLLM())
    engine._ensure_mind("c1", "Blacktide")

    await engine.update_npc_thoughts("c1", "Blackthorn appeared", "world context")

    minds = engine.get_all_minds("c1")
    assert len(minds) == 2


@pytest.mark.asyncio
async def test_dedup_aliases_prevent_recheck():
    """Once alias is recorded, no LLM dedup call on reuse."""
    call_count = 0

    class CountingLLM:
        async def complete(self, messages, **kwargs):
            nonlocal call_count
            call_count += 1
            content = messages[-1]["content"] if messages else ""
            if "world context" in content.lower() or "narrative" in content.lower():
                return json.dumps({
                    "npcs": [{"name": "Blacktide", "thoughts": {"feeling": "calm"}}]
                })
            if "same character" in messages[0]["content"].lower():
                return "YES"
            return "{}"

    engine = NpcMindEngine(llm=CountingLLM())
    engine._ensure_mind("c1", "Captain Blacktide")

    await engine.update_npc_thoughts("c1", "Blacktide spoke", "world context")
    first_call_count = call_count

    await engine.update_npc_thoughts("c1", "Blacktide nodded", "world context")
    # Only NPC extraction call, no dedup check
    assert call_count == first_call_count + 1
