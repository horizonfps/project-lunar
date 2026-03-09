from __future__ import annotations
import random
from dataclasses import dataclass
from enum import Enum

from app.utils.json_parsing import parse_json_dict


class CombatOutcome(str, Enum):
    CRIT_FAIL = "CRIT_FAIL"
    FAIL = "FAIL"
    SUCCESS = "SUCCESS"
    CRIT_SUCCESS = "CRIT_SUCCESS"


@dataclass
class ActionEvaluation:
    coherence: float
    creativity: float
    context: float
    final_quality: float


@dataclass
class AntiGriefingResult:
    rejected: bool
    reason: str = ""


class CombatEngine:
    def __init__(self, llm):
        self._llm = llm

    async def anti_griefing_check(self, action: str) -> AntiGriefingResult:
        messages = [
            {
                "role": "system",
                "content": (
                    "Analyze this combat action for griefing. Return ONLY JSON: "
                    '{"is_meta": bool, "is_physically_impossible": bool}. '
                    "is_meta=true if the player claims victory by narrative fiat or authorial power. "
                    "is_physically_impossible=true if the action completely defies physics "
                    "(teleportation, omnidirectional attacks, infinite force, etc.)."
                ),
            },
            {"role": "user", "content": action},
        ]
        raw = await self._llm.complete(messages=messages)
        data = parse_json_dict(raw)
        if not data:
            return AntiGriefingResult(rejected=False)

        if data.get("is_meta"):
            return AntiGriefingResult(
                rejected=True,
                reason="Meta-gaming attempt: claiming victory by narrative authority.",
            )
        if data.get("is_physically_impossible"):
            return AntiGriefingResult(
                rejected=True,
                reason="Physically impossible action rejected.",
            )
        return AntiGriefingResult(rejected=False)

    async def evaluate_action(
        self,
        action: str,
        npc_name: str,
        npc_power: int,
    ) -> ActionEvaluation:
        messages = [
            {
                "role": "system",
                "content": (
                    "Score this combat action on 3 dimensions (0-10 each). "
                    "Return ONLY JSON: "
                    '{"coherence": N, "creativity": N, "context": N}. '
                    "coherence: physical/logical feasibility (can a human actually do this?). "
                    "creativity: tactical originality and detail — NOT text length. "
                    "context: situational appropriateness for this opponent. "
                    "A short creative action beats a long incoherent one."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Action: {action}\n"
                    f"Opponent: {npc_name} (power {npc_power}/10)"
                ),
            },
        ]
        raw = await self._llm.complete(messages=messages)
        data = parse_json_dict(raw)
        if not data:
            coherence = creativity = context = 5.0
        else:
            try:
                coherence = float(data.get("coherence", 5))
                creativity = float(data.get("creativity", 5))
                context = float(data.get("context", 5))
            except (TypeError, ValueError):
                coherence = creativity = context = 5.0

        final_quality = coherence * 0.4 + creativity * 0.4 + context * 0.2
        return ActionEvaluation(
            coherence=coherence,
            creativity=creativity,
            context=context,
            final_quality=final_quality,
        )

    def roll_outcome(self, action_quality: float, npc_power: int) -> CombatOutcome:
        """
        action_quality: 0-10
        npc_power: 1-10
        Calculates outcome probability and rolls.
        """
        q = max(0.0, min(10.0, action_quality)) / 10.0   # normalize 0-1
        d = max(1, min(10, npc_power)) / 10.0             # normalize 0-1

        # Base success probability: quality drives success, difficulty opposes it
        success_prob = q * 0.65 + (1.0 - d) * 0.35

        roll = random.random()

        # Crit fail: only possible when quality is below 0.75 (action_quality < 7.5/10)
        # Both low quality AND high difficulty required
        crit_fail_threshold = max(0.0, (0.75 - q)) * d * 0.4
        # Crit success: only possible when quality is above 0.25 (action_quality > 2.5/10)
        # Requires high quality and low difficulty
        crit_success_threshold = max(0.0, (q - 0.25)) * (1.0 - d) * 0.25

        if roll < crit_fail_threshold:
            return CombatOutcome.CRIT_FAIL
        if roll > (1.0 - crit_success_threshold):
            return CombatOutcome.CRIT_SUCCESS
        if roll < success_prob:
            return CombatOutcome.SUCCESS
        return CombatOutcome.FAIL
