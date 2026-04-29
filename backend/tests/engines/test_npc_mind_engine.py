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


# ── Camada 3 — perspective filter (npcs_present) ───────────────────


class _RecordingLLM:
    """LLM stub that records the last user-content prompt for inspection."""
    def __init__(self, response: str):
        self._response = response
        self.last_user_content = ""
        self.last_system_content = ""

    async def complete(self, messages, **kwargs):
        self.last_system_content = messages[0]["content"] if messages else ""
        self.last_user_content = messages[-1]["content"] if messages else ""
        return self._response


@pytest.mark.asyncio
async def test_npcs_present_filter_drops_off_screen_npcs():
    """When npcs_present is provided, NPCs not in the list are silently dropped."""
    response = json.dumps({
        "npcs": [
            {"name": "Rin", "thoughts": {"feeling": "alert"}},
            {"name": "Yumi", "thoughts": {"feeling": "asleep"}},  # off-screen — must drop
        ]
    })
    engine = NpcMindEngine(llm=_RecordingLLM(response))
    updated = await engine.update_npc_thoughts(
        campaign_id="c1",
        narrative_text="Rin nodded.",
        world_context="ctx",
        npcs_present=["Rin"],
    )
    names = {m.name for m in updated}
    assert names == {"Rin"}


@pytest.mark.asyncio
async def test_npcs_present_empty_list_keeps_legacy_behavior():
    """Empty / None npcs_present means no filtering — backward compat."""
    response = json.dumps({
        "npcs": [
            {"name": "Rin", "thoughts": {"feeling": "alert"}},
            {"name": "Yumi", "thoughts": {"feeling": "calm"}},
        ]
    })
    engine = NpcMindEngine(llm=_RecordingLLM(response))
    updated = await engine.update_npc_thoughts(
        campaign_id="c1",
        narrative_text="Rin and Yumi spoke.",
        world_context="ctx",
        # npcs_present omitted
    )
    names = {m.name for m in updated}
    assert names == {"Rin", "Yumi"}


@pytest.mark.asyncio
async def test_npc_knowledge_block_injected_into_prompt():
    """Per-NPC knowledge maps appear in the user prompt for the LLM."""
    response = json.dumps({"npcs": [{"name": "Rin", "thoughts": {"feeling": "calm"}}]})
    llm = _RecordingLLM(response)
    engine = NpcMindEngine(llm=llm)
    await engine.update_npc_thoughts(
        campaign_id="c1",
        narrative_text="Rin nodded.",
        world_context="ctx",
        npcs_present=["Rin"],
        npc_knowledge={"Rin": "Rin saw the duel last week."},
    )
    assert "NPC KNOWLEDGE BOUNDARIES" in llm.last_user_content
    assert "Rin saw the duel last week" in llm.last_user_content


@pytest.mark.asyncio
async def test_scene_presence_constraint_appears_in_system_prompt():
    """The system prompt explicitly lists which NPCs the LLM can write about."""
    response = json.dumps({"npcs": [{"name": "Rin", "thoughts": {"feeling": "calm"}}]})
    llm = _RecordingLLM(response)
    engine = NpcMindEngine(llm=llm)
    await engine.update_npc_thoughts(
        campaign_id="c1",
        narrative_text="A short scene.",
        world_context="ctx",
        npcs_present=["Rin", "Kai"],
    )
    assert "SCENE PRESENCE" in llm.last_system_content
    assert "Rin" in llm.last_system_content
    assert "Kai" in llm.last_system_content


# ── Camada 4 — decay + factual/narrative split + personality anchors ──


@pytest.mark.asyncio
async def test_feeling_decays_after_default_window():
    """A 'feeling' thought set at turn 10 should be dropped at turn 15+."""
    response = json.dumps({
        "npcs": [{"name": "Rin", "thoughts": {"feeling": "anxious"}}]
    })
    engine = NpcMindEngine(llm=FakeLLM(response))
    await engine.update_npc_thoughts(
        campaign_id="c1",
        narrative_text="Rin paces.",
        world_context="ctx",
        current_turn=10,
    )
    mind = engine.get_mind("c1", "Rin")
    assert mind.get_thought("feeling") == "anxious"

    # Apply decay at turn 15 (age=5, default decay_after_turns for feeling=5).
    dropped = engine.apply_decay(mind, current_turn=15)
    assert "feeling" in dropped
    assert mind.get_thought("feeling") is None


@pytest.mark.asyncio
async def test_goal_never_decays():
    """Goals are persistent — apply_decay must keep them indefinitely."""
    response = json.dumps({
        "npcs": [{"name": "Rin", "thoughts": {"goal": "find her brother"}}]
    })
    engine = NpcMindEngine(llm=FakeLLM(response))
    await engine.update_npc_thoughts(
        campaign_id="c1",
        narrative_text="Rin sets out.",
        world_context="ctx",
        current_turn=1,
    )
    mind = engine.get_mind("c1", "Rin")
    # Even after 1000 turns, goal must survive.
    dropped = engine.apply_decay(mind, current_turn=1001)
    assert "goal" not in dropped
    assert mind.get_thought("goal") == "find her brother"


@pytest.mark.asyncio
async def test_apply_decay_all_drops_only_expired():
    """apply_decay_all should expire transient thoughts but preserve persistent ones."""
    response = json.dumps({
        "npcs": [{
            "name": "Kai",
            "thoughts": {
                "feeling": "tense",
                "goal": "guard the gate",
                "secret_plan": "report to captain",
            },
        }]
    })
    engine = NpcMindEngine(llm=FakeLLM(response))
    await engine.update_npc_thoughts(
        campaign_id="c1",
        narrative_text="Kai watches.",
        world_context="ctx",
        current_turn=20,
    )
    dropped = engine.apply_decay_all("c1", current_turn=30)
    assert dropped == {"Kai": ["feeling"]}
    mind = engine.get_mind("c1", "Kai")
    assert mind.get_thought("feeling") is None
    assert mind.get_thought("goal") == "guard the gate"
    assert mind.get_thought("secret_plan") == "report to captain"


@pytest.mark.asyncio
async def test_factual_context_appears_in_user_prompt():
    """Camada 4 — factual_context must be rendered as a separate canon block."""
    response = json.dumps({"npcs": [{"name": "Rin", "thoughts": {"feeling": "calm"}}]})
    llm = _RecordingLLM(response)
    engine = NpcMindEngine(llm=llm)
    await engine.update_npc_thoughts(
        campaign_id="c1",
        narrative_text="Rin nods.",
        world_context="mutable scene state",
        factual_context="=== PRMNT_MEM (canon) ===\nThe sun rises in the east.",
        current_turn=1,
    )
    assert "FACTUAL CONTEXT" in llm.last_user_content
    assert "The sun rises in the east" in llm.last_user_content
    assert "NARRATIVE CONTEXT" in llm.last_user_content
    assert "mutable scene state" in llm.last_user_content


@pytest.mark.asyncio
async def test_personality_anchors_appear_in_user_prompt():
    """Per-NPC anchors must be rendered as PERSONALITY ANCHORS block."""
    response = json.dumps({"npcs": [{"name": "Rin", "thoughts": {"feeling": "calm"}}]})
    llm = _RecordingLLM(response)
    engine = NpcMindEngine(llm=llm)
    anchors = {
        "Rin": "core_trait: loyal but pragmatic\ndo_not_drift_to: paranoid stalker",
    }
    await engine.update_npc_thoughts(
        campaign_id="c1",
        narrative_text="Rin nods.",
        world_context="ctx",
        personality_anchors=anchors,
        current_turn=1,
    )
    assert "PERSONALITY ANCHORS" in llm.last_user_content
    assert "Rin" in llm.last_user_content
    assert "loyal but pragmatic" in llm.last_user_content
    assert "paranoid stalker" in llm.last_user_content


@pytest.mark.asyncio
async def test_canon_rules_appear_in_system_prompt():
    """The system prompt grows a CANON RULES block instructing the LLM to anchor."""
    response = json.dumps({"npcs": [{"name": "Rin", "thoughts": {"feeling": "calm"}}]})
    llm = _RecordingLLM(response)
    engine = NpcMindEngine(llm=llm)
    await engine.update_npc_thoughts(
        campaign_id="c1",
        narrative_text="Rin nods.",
        world_context="ctx",
        current_turn=1,
    )
    assert "CANON RULES" in llm.last_system_content
    assert "FACTUAL CONTEXT" in llm.last_system_content
    assert "PERSONALITY ANCHORS" in llm.last_system_content


@pytest.mark.asyncio
async def test_set_thought_uses_default_decay_for_feeling():
    """NpcMind.set_thought must look up THOUGHT_DECAY_DEFAULTS by default."""
    from app.engines.npc_mind_engine import NpcMind, THOUGHT_DECAY_DEFAULTS

    mind = NpcMind(name="Test", campaign_id="c1")
    mind.set_thought("feeling", "happy", current_turn=5)
    t = mind.thoughts["feeling"]
    assert t.created_at_turn == 5
    assert t.decay_after_turns == THOUGHT_DECAY_DEFAULTS["feeling"] == 5

    mind.set_thought("goal", "explore", current_turn=5)
    g = mind.thoughts["goal"]
    assert g.decay_after_turns is None  # never decays


@pytest.mark.asyncio
async def test_set_thought_explicit_decay_override():
    """Explicit decay_after_turns argument must override the default table."""
    from app.engines.npc_mind_engine import NpcMind

    mind = NpcMind(name="Test", campaign_id="c1")
    mind.set_thought("feeling", "happy", current_turn=5, decay_after_turns=20)
    assert mind.thoughts["feeling"].decay_after_turns == 20

    # Explicit None means "never decay" — distinct from "use default".
    mind.set_thought("feeling", "anxious", current_turn=5, decay_after_turns=None)
    assert mind.thoughts["feeling"].decay_after_turns is None


@pytest.mark.asyncio
async def test_apply_decay_no_op_when_turn_zero():
    """current_turn=0 (no turn tracking) must not drop anything."""
    from app.engines.npc_mind_engine import NpcMind

    mind = NpcMind(name="Test", campaign_id="c1")
    mind.set_thought("feeling", "happy", current_turn=0)
    engine = NpcMindEngine(llm=FakeLLM())
    dropped = engine.apply_decay(mind, current_turn=0)
    assert dropped == []
    assert mind.get_thought("feeling") == "happy"
