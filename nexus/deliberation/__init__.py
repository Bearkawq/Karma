"""
Deliberation Chamber - Where I-Positions debate and vote

Each task goes through:
1. Input - Task presented to all voices
2. Position Formulation - Each voice develops their approach
3. Debate - Voices present, challenge others
4. Voting - Decision made (or escalate)
5. Dissent Recording - Minority opinions stored for revisit
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional
import time

from core import (
    NexusCore, IPosition, VoiceContribution, Decision, IPositionType
)


class DecisionScope(Enum):
    """Size of decision determines required consensus."""
    SMALL = "small"      # Any single voice can decide (within budget)
    MEDIUM = "medium"   # Requires 2+ voices agree
    LARGE = "large"     # Requires 3+ voices agree + human available
    CRITICAL = "critical"  # Requires all voices + human approval


@dataclass
class DeliberationResult:
    """Result of a deliberation session."""
    decision: Decision
    contributions: list[VoiceContribution] = field(default_factory=list)
    debate_log: list[str] = field(default_factory=list)
    overseer_intervention: Optional[str] = None


class DeliberationChamber:
    """Manages the deliberation process between I-Positions."""
    
    def __init__(self, nexus: NexusCore):
        self.nexus = nexus
        self.llm_provider: Optional[Callable] = None
    
    def set_llm_provider(self, provider: Callable):
        """Set the LLM function to use for generation."""
        self.llm_provider = provider
    
    def _classify_decision_scope(self, task: str) -> DecisionScope:
        """Classify the scope of a task."""
        task_lower = task.lower()
        
        # Critical: system changes, deletions, financial
        critical_keywords = ["delete", "remove", "destroy", "cancel", "paid", "money"]
        if any(kw in task_lower for kw in critical_keywords):
            return DecisionScope.CRITICAL
        
        # Large: file creation, deployments, multiple steps
        large_keywords = ["create", "deploy", "build", "install", "setup"]
        if any(kw in task_lower for kw in large_keywords):
            return DecisionScope.LARGE
        
        # Medium: configuration, modifications
        medium_keywords = ["modify", "change", "update", "config", "edit"]
        if any(kw in task_lower for kw in medium_keywords):
            return DecisionScope.MEDIUM
        
        # Default: small queries, read operations
        return DecisionScope.SMALL
    
    def _get_required_votes(self, scope: DecisionScope) -> int:
        """Get number of votes required for each scope."""
        return {
            DecisionScope.SMALL: 1,
            DecisionScope.MEDIUM: 2,
            DecisionScope.LARGE: 3,
            DecisionScope.CRITICAL: 4,
        }[scope]
    
    async def deliberate(self, task: str, context: str = "") -> DeliberationResult:
        """Run deliberation on a task."""
        scope = self._classify_decision_scope(task)
        required_votes = self._get_required_votes(scope)
        
        contributions: list[VoiceContribution] = []
        debate_log: list[str] = []
        
        # Phase 1: Each voice formulates position
        for voice in self.nexus.voices:
            position_text = await self._formulate_position(voice, task, context)
            contribution = VoiceContribution(
                voice=voice,
                position=position_text.split("|")[0].strip() if "|" in position_text else position_text,
                reasoning=position_text.split("|")[1].strip() if "|" in position_text else "",
                confidence=0.7  # Will be updated after debate
            )
            contributions.append(contribution)
            debate_log.append(f"[{voice.name}] proposes: {contribution.position}")
        
        # Phase 2: Debate (simplified - in real version would be iterative)
        debate_log.append("\n--- DEBATE PHASE ---")
        for contribution in contributions:
            challenges = await self._generate_challenges(contribution, contributions, task)
            debate_log.append(f"[{voice.name}] challenges: {challenges}")
        
        # Phase 3: Voting
        debate_log.append("\n--- VOTING PHASE ---")
        votes = await self._collect_votes(contributions, task, scope)
        
        # Phase 4: Determine outcome
        chosen_path, confidence, dissent = self._resolve_votes(
            votes, contributions, required_votes
        )
        
        # Check if human approval needed
        requires_human = (
            scope == DecisionScope.CRITICAL or
            confidence < 0.5 or
            len(dissent) >= 2
        )
        
        decision = Decision(
            task=task,
            decision_type=scope.value,
            choices_considered=[c.position for c in contributions],
            chosen_path=chosen_path,
            votes=votes,
            dissent_recorded=dissent,
            confidence=confidence,
            requires_human=requires_human
        )
        
        # Check overseer
        overseer_intervention = await self._check_overseer(decision, contributions)
        
        return DeliberationResult(
            decision=decision,
            contributions=contributions,
            debate_log=debate_log,
            overseer_intervention=overseer_intervention
        )
    
    async def _formulate_position(
        self, voice: IPosition, task: str, context: str
    ) -> str:
        """Get voice's position on the task."""
        if self.llm_provider:
            prompt = f"""You are {voice.name}, {voice.description}.
Your strengths: {', '.join(voice.strengths)}
Your weaknesses: {', '.join(voice.weaknesses)}

Task: {task}
Context: {context}

Provide your position on how to handle this task.
Format: POSITION|REASONING
"""
            return await self.llm_provider(prompt)
        
        # Fallback without LLM
        return f"{voice.name} approaches task cautiously|{voice.description}"
    
    async def _generate_challenges(
        self, contribution: VoiceContribution,
        all_contributions: list[VoiceContribution], task: str
    ) -> str:
        """Generate challenges from other voices."""
        if self.llm_provider:
            prompt = f"""As {contribution.voice.name}, challenge the other approaches.
Other positions: {[c.position for c in all_contributions if c.voice != contribution.voice]}

Provide a brief challenge.
"""
            return await self.llm_provider(prompt)
        return "Consider alternative approaches."
    
    async def _collect_votes(
        self, contributions: list[VoiceContribution], 
        task: str, scope: DecisionScope
    ) -> dict[str, str]:
        """Collect votes from each voice."""
        votes = {}
        
        for contribution in contributions:
            if self.llm_provider:
                vote_prompt = f"""You are {contribution.voice.name}.
Task: {task}
Your position: {contribution.position}

Vote: support, oppose, or abstain?
Just give one word.
"""
                vote = (await self.llm_provider(vote_prompt)).strip().lower()
                if vote not in ["support", "oppose", "abstain"]:
                    vote = "support"
            else:
                vote = "support"
            
            votes[contribution.voice.name] = vote
            contribution.vote = vote
        
        return votes
    
    def _resolve_votes(
        self, votes: dict[str, str], contributions: list[VoiceContribution],
        required_votes: int
    ) -> tuple[str, float, list[VoiceContribution]]:
        """Resolve votes to determine outcome."""
        support_count = sum(1 for v in votes.values() if v == "support")
        oppose_count = sum(1 for v in votes.values() if v == "oppose")
        
        # Get dissenters
        dissent = [c for c in contributions if votes.get(c.voice.name) == "oppose"]
        
        # Determine chosen path
        if support_count >= required_votes:
            # Find the most supported position
            chosen = max(contributions, key=lambda c: 
                1 if votes.get(c.voice.name) == "support" else 0)
            chosen_path = chosen.position
            confidence = support_count / len(self.nexus.voices)
        elif oppose_count >= required_votes:
            # Blocked - need human
            chosen_path = "BLOCKED - requires human decision"
            confidence = 0.0
        else:
            # No clear majority - use highest confidence
            chosen = max(contributions, key=lambda c: c.confidence)
            chosen_path = chosen.position
            confidence = 0.4  # Lower confidence
        
        return chosen_path, confidence, dissent
    
    async def _check_overseer(
        self, decision: Decision, contributions: list[VoiceContribution]
    ) -> Optional[str]:
        """Check if overseer should intervene."""
        # Intervene on low confidence
        if decision.confidence < 0.5:
            return f"OVERSEER: Low confidence ({decision.confidence:.0%}). Human review recommended."
        
        # Intervene on strong dissent
        if len(decision.dissent_recorded) >= 2:
            return f"OVERSEER: Strong dissent ({len(decision.dissent_recorded)} voices opposed)."
        
        # Intervene on similar recent decisions that failed
        # (would check memory in real implementation)
        
        return None
