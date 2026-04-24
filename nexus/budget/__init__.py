"""
Bounded Autonomy Budget System

Each role has a decision budget:
- Small decisions: Within role's autonomy (no approval needed)
- Medium decisions: Need 2+ voices agree
- Large decisions: Need 3+ voices agree + human available
- Critical decisions: Need all voices + human explicit approval

This prevents runaway agent behavior.
"""

from dataclasses import dataclass, field
from enum import Enum
import time


class DecisionScope(Enum):
    SMALL = "small"      # < $10, no risk, reversible
    MEDIUM = "medium"   # < $100, low risk, mostly reversible
    LARGE = "large"     # < $1000, moderate risk, requires thought
    CRITICAL = "critical"  # > $1000, high risk, irreversible


@dataclass
class BudgetEntry:
    """A decision made within a budget."""
    scope: DecisionScope
    description: str
    voices_approved: list[str] = field(default_factory=list)
    human_approved: bool = False
    timestamp: float = field(default_factory=time.time)
    reversed: bool = False


@dataclass
class VoiceBudget:
    """Budget allocation for a single voice."""
    voice_name: str
    small_decisions_remaining: int = 10  # Per hour
    medium_decisions_remaining: int = 5   # Per hour
    large_decisions_remaining: int = 2   # Per hour
    critical_decisions_remaining: int = 1 # Per day
    hourly_reset: float = field(default_factory=time.time)

    def can_decide(self, scope: DecisionScope) -> bool:
        """Check if this voice can make a decision of given scope."""
        self._reset_if_needed()

        if scope == DecisionScope.SMALL:
            return self.small_decisions_remaining > 0
        elif scope == DecisionScope.MEDIUM:
            return self.medium_decisions_remaining > 0
        elif scope == DecisionScope.LARGE:
            return self.large_decisions_remaining > 0
        else:
            return self.critical_decisions_remaining > 0

    def spend(self, scope: DecisionScope):
        """Spend a budget allocation."""
        self._reset_if_needed()

        if scope == DecisionScope.SMALL:
            self.small_decisions_remaining -= 1
        elif scope == DecisionScope.MEDIUM:
            self.medium_decisions_remaining -= 1
        elif scope == DecisionScope.LARGE:
            self.large_decisions_remaining -= 1
        else:
            self.critical_decisions_remaining -= 1

    def _reset_if_needed(self):
        """Reset hourly budgets."""
        now = time.time()
        if now - self.hourly_reset > 3600:
            self.small_decisions_remaining = 10
            self.medium_decisions_remaining = 5
            self.large_decisions_remaining = 2
            self.hourly_reset = now


class BoundedAutonomySystem:
    """Enforces decision budgets across all voices."""

    def __init__(self, voices: list[str]):
        self.voice_budgets = {name: VoiceBudget(name) for name in voices}
        self.decision_history: list[BudgetEntry] = []

    def classify_decision(self, description: str) -> DecisionScope:
        """Classify a decision by its scope/risk."""
        desc_lower = description.lower()

        # Critical keywords
        critical = ["delete", "remove", "destroy", "cancel", "paid", "money", "transfer"]
        if any(kw in desc_lower for kw in critical):
            return DecisionScope.CRITICAL

        # Large keywords
        large = ["create", "deploy", "build", "install", "setup", "buy", "purchase"]
        if any(kw in desc_lower for kw in large):
            return DecisionScope.LARGE

        # Medium keywords
        medium = ["modify", "change", "update", "config", "edit", "write"]
        if any(kw in desc_lower for kw in medium):
            return DecisionScope.MEDIUM

        return DecisionScope.SMALL

    def check_approval(
        self, scope: DecisionScope,
        agreeing_voices: list[str],
        human_available: bool = False
    ) -> tuple[bool, str]:
        """Check if decision can be approved."""

        # Critical always needs human
        if scope == DecisionScope.CRITICAL:
            if not human_available:
                return False, "CRITICAL: Human approval required but no human available"
            if len(agreeing_voices) < len(self.voice_budgets):
                return False, "CRITICAL: All voices must agree"
            return True, "CRITICAL: Approved by all voices and human"

        # Large needs 3+ voices or human
        if scope == DecisionScope.LARGE:
            if len(agreeing_voices) >= 3:
                return True, f"LARGE: Approved by {len(agreeing_voices)} voices"
            if human_available:
                return True, f"LARGE: Approved with human override ({len(agreeing_voices)} voices)"
            return False, f"LARGE: Need 3+ voices or human (have {len(agreeing_voices)})"

        # Medium needs 2+ voices
        if scope == DecisionScope.MEDIUM:
            if len(agreeing_voices) >= 2:
                return True, f"MEDIUM: Approved by {len(agreeing_voices)} voices"
            return False, f"MEDIUM: Need 2+ voices (have {len(agreeing_voices)})"

        # Small needs 1 voice with budget
        if len(agreeing_voices) >= 1:
            for voice in agreeing_voices:
                if voice in self.voice_budgets:
                    if self.voice_budgets[voice].can_decide(DecisionScope.SMALL):
                        return True, f"SMALL: Approved by {voice}"

        return False, "SMALL: No voice with available budget"

    def record_decision(
        self, scope: DecisionScope, description: str,
        voices_approved: list[str], human_approved: bool = False
    ):
        """Record a decision and update budgets."""
        entry = BudgetEntry(
            scope=scope,
            description=description,
            voices_approved=voices_approved,
            human_approved=human_approved
        )
        self.decision_history.append(entry)

        # Spend budgets
        for voice in voices_approved:
            if voice in self.voice_budgets:
                self.voice_budgets[voice].spend(scope)

    def get_status(self) -> str:
        """Get budget status for all voices."""
        lines = ["=== BUDGET STATUS ==="]
        for name, budget in self.voice_budgets.items():
            lines.append(
                f"{name}: S:{budget.small_decisions_remaining} "
                f"M:{budget.medium_decisions_remaining} "
                f"L:{budget.large_decisions_remaining} "
                f"C:{budget.critical_decisions_remaining}"
            )
        return "\n".join(lines)

    def summary(self) -> str:
        """Get quick summary."""
        total = sum(len(e.voices_approved) for e in self.decision_history)
        return f"Decisions made: {len(self.decision_history)}, Voices involved: {total}"
