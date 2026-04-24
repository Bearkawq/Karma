"""
NEXUS - A Multi-Voice Deliberative Agent System

A society of minds where multiple internal voices (I-Posesitions) debate,
plan, and execute tasks with a meta-cognitive overseer.

Core concept: Not just multi-agent, but multi-voice deliberative.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
import time
import uuid


class IPositionType(Enum):
    PLANNER = "planner"
    EXECUTOR = "executor"
    CRITIC = "critic"
    DEVILS_ADVOCATE = "devils_advocate"
    OVERSEER = "overseer"


@dataclass
class IPosition:
    """Represents a voice in the deliberation chamber."""
    name: str
    role_type: IPositionType
    description: str
    strengths: list[str] = field(default_factory=list)
    weaknesses: list[str] = field(default_factory=list)
    decision_style: str = "balanced"  # aggressive, cautious, balanced
    creativity: int = 5  # 1-10
    skepticism: int = 5  # 1-10

    def __post_init__(self):
        if not self.name:
            self.name = self.role_type.value.capitalize()


@dataclass
class VoiceContribution:
    """A single voice's contribution to deliberation."""
    voice: IPosition
    position: str
    reasoning: str
    confidence: float  # 0.0 to 1.0
    timestamp: float = field(default_factory=time.time)
    vote: Optional[str] = None  # support, oppose, abstain


@dataclass
class Decision:
    """A decision made through deliberation."""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    task: str = ""
    decision_type: str = ""  # small, medium, large
    choices_considered: list[str] = field(default_factory=list)
    chosen_path: str = ""
    votes: dict[str, str] = field(default_factory=dict)  # voice_name -> vote
    dissent_recorded: list[VoiceContribution] = field(default_factory=list)
    confidence: float = 0.0
    requires_human: bool = False
    timestamp: float = field(default_factory=time.time)
    outcome: Optional[str] = None


@dataclass
class ExecutionResult:
    """Result of executing a decision."""
    decision_id: str
    success: bool
    output: str
    errors: list[str] = field(default_factory=list)
    duration_seconds: float = 0.0
    timestamp: float = field(default_factory=time.time)


class NexusCore:
    """Core NEXUS system with I-Position voices."""

    def __init__(self):
        self.voices = self._create_voices()
        self.overseer = self._create_overseer()
        self.history: list[Decision] = []
        self.deliberation_count = 0

    def _create_voices(self) -> list[IPosition]:
        """Create the 4 primary I-Position voices."""
        return [
            IPosition(
                name="Architect",
                role_type=IPositionType.PLANNER,
                description="Focuses on structure, strategy, and long-term goals",
                strengths=["big picture", "strategic thinking", "breakdown"],
                weaknesses=["details", "tactical execution"],
                decision_style="balanced",
                creativity=8,
                skepticism=4
            ),
            IPosition(
                name="Builder",
                role_type=IPositionType.EXECUTOR,
                description="Focuses on action, implementation, and getting things done",
                strengths=["action", "pragmatism", "speed"],
                weaknesses=["analysis", "caution"],
                decision_style="aggressive",
                creativity=5,
                skepticism=3
            ),
            IPosition(
                name="Sentinel",
                role_type=IPositionType.CRITIC,
                description="Focuses on risks, flaws, and edge cases",
                strengths=["risk analysis", "quality", "thoroughness"],
                weaknesses=["over-critical", "slow"],
                decision_style="cautious",
                creativity=3,
                skepticism=9
            ),
            IPosition(
                name="Provocateur",
                role_type=IPositionType.DEVILS_ADVOCATE,
                description="Challenges assumptions and finds alternative perspectives",
                strengths=["alternatives", "edge cases", "creative challenges"],
                weaknesses=["can stall", "can be negative"],
                decision_style="balanced",
                creativity=9,
                skepticism=7
            )
        ]

    def _create_overseer(self) -> IPosition:
        """Create the metacognitive overseer."""
        return IPosition(
            name="Overseer",
            role_type=IPositionType.OVERSEER,
            description="Monitors deliberation, intervenes on low confidence or loops",
            strengths=["meta-cognition", "pattern recognition", "timing"],
            weaknesses=["can be silent too long"],
            decision_style="balanced",
            creativity=6,
            skepticism=6
        )

    def get_voice(self, role_type: IPositionType) -> Optional[IPosition]:
        """Get a specific voice by type."""
        if role_type == IPositionType.OVERSEER:
            return self.overseer
        for voice in self.voices:
            if voice.role_type == role_type:
                return voice
        return None

    def list_voices(self) -> list[str]:
        """List all voice names."""
        return [v.name for v in self.voices] + [self.overseer.name]

    def get_architecture_summary(self) -> str:
        """Get a summary of the NEXUS architecture."""
        summary = "NEXUS Multi-Voice Deliberative System\n"
        summary += "=" * 50 + "\n\n"
        summary += "I-POSITION VOICES:\n"
        for voice in self.voices:
            summary += f"  • {voice.name} ({voice.role_type.value}): {voice.description}\n"
            summary += f"    Strengths: {', '.join(voice.strengths)}\n\n"
        summary += "\nMETACOGNITIVE OVERSEER:\n"
        summary += f"  • {self.overseer.name}: {self.overseer.description}\n"
        summary += "    Intervenes when: confidence < 50% or agents looping\n"
        return summary


# Default instance
nexus = NexusCore()
