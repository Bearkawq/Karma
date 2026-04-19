"""
Failure Archaeology - Dig 3 Layers Deep on Failures

When something fails, we systematically dig:
- Layer 1: Surface Error - What directly failed?
- Layer 2: Root Cause - Why did it fail at that point?
- Layer 3: Pattern Discovery - Is this part of a larger pattern?

This is NOT just "learn from mistakes" - it's archaeological excavation.
"""

from dataclasses import dataclass, field
from typing import Optional
from enum import Enum
import time
import uuid


class FailureDepth(Enum):
    SURFACE = "surface"      # Layer 1: What happened
    ROOT = "root"            # Layer 2: Why it happened
    PATTERN = "pattern"      # Layer 3: Is this a pattern?


@dataclass
class ExcavationLayer:
    """One layer of failure excavation."""
    depth: FailureDepth
    finding: str
    evidence: list[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)


@dataclass
class Excavation:
    """Complete archaeological dig on a failure."""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    initial_failure: str = ""
    layers: list[ExcavationLayer] = field(default_factory=list)
    pattern_found: Optional[str] = None
    recommendation: str = ""
    created_at: float = field(default_factory=time.time)
    
    def add_layer(self, depth: FailureDepth, finding: str, evidence: list[str] = None):
        """Add an excavation layer."""
        self.layers.append(ExcavationLayer(
            depth=depth,
            finding=finding,
            evidence=evidence or []
        ))
    
    def summary(self) -> str:
        """Get summary of excavation."""
        lines = [f"Excavation {self.id}: {self.initial_failure}"]
        for layer in self.layers:
            lines.append(f"  [{layer.depth.value.upper()}] {layer.finding}")
        if self.pattern_found:
            lines.append(f"  PATTERN: {self.pattern_found}")
        if self.recommendation:
            lines.append(f"  REC: {self.recommendation}")
        return "\n".join(lines)


class FailureArchaeologist:
    """Digs into failures systematically."""
    
    def __init__(self, memory):
        self.memory = memory  # Reference to temporal-intensity memory
    
    async def excavate(
        self, failure_description: str, 
        context: str = "", 
        llm_provider=None
    ) -> Excavation:
        """Excavate a failure to 3 layers deep."""
        excavation = Excavation(initial_failure=failure_description)
        
        # Layer 1: Surface Error
        surface = await self._dig_surface(failure_description, context, llm_provider)
        excavation.add_layer(FailureDepth.SURFACE, surface["finding"], surface["evidence"])
        
        # Layer 2: Root Cause
        root = await self._dig_root(failure_description, surface["finding"], context, llm_provider)
        excavation.add_layer(FailureDepth.ROOT, root["finding"], root["evidence"])
        
        # Layer 3: Pattern Discovery
        pattern = await self._dig_pattern(failure_description, root["finding"], excavation, llm_provider)
        if pattern["pattern"]:
            excavation.pattern_found = pattern["pattern"]
            excavation.add_layer(FailureDepth.PATTERN, pattern["finding"], pattern["evidence"])
        
        # Generate recommendation
        excavation.recommendation = await self._generate_recommendation(
            excavation, llm_provider
        )
        
        # Store in memory with high intensity
        self.memory.add(
            content=failure_description,
            context=excavation.summary(),
            outcome="failure",
            emotional_intensity=0.9,
            tags=["failure", "archaeology", excavation.pattern_found or "no-pattern"]
        )
        
        return excavation
    
    async def _dig_surface(
        self, failure: str, context: str, llm
    ) -> dict:
        """Layer 1: What directly failed?"""
        if llm:
            prompt = f"""Analyze this failure: {failure}
Context: {context}

Layer 1 - Surface Error:
What directly failed? What was the immediate error or issue?

Provide: finding and evidence (list of specific observations)
"""
            result = await llm(prompt)
            return {"finding": result, "evidence": [f"Direct failure: {failure}"]}
        
        return {
            "finding": f"The task '{failure}' did not achieve its intended outcome.",
            "evidence": [f"Initial failure report: {failure}"]
        }
    
    async def _dig_root(
        self, failure: str, surface_finding: str, context: str, llm
    ) -> dict:
        """Layer 2: Why did it fail at that point?"""
        if llm:
            prompt = f"""Previous analysis: {surface_finding}
Original failure: {failure}
Context: {context}

Layer 2 - Root Cause:
Why did this failure occur? Trace back to the underlying cause.

Provide: finding and evidence (the chain of causation)
"""
            result = await llm(prompt)
            return {"finding": result, "evidence": [f"Surface: {surface_finding}"]}
        
        return {
            "finding": "Root cause analysis pending - LLM not available.",
            "evidence": [f"Surface finding: {surface_finding}"]
        }
    
    async def _dig_pattern(
        self, failure: str, root_finding: str, excavation: Excavation, llm
    ) -> dict:
        """Layer 3: Is this part of a larger pattern?"""
        # Check memory for similar failures
        similar = self.memory.recall(failure, top_k=10)
        similar_failures = [e for e in similar if e.outcome == "failure"]
        
        if len(similar_failures) < 2:
            return {
                "pattern": None,
                "finding": "No pattern detected - first occurrence or isolated incident.",
                "evidence": [f"Found {len(similar_failures)} similar failures"]
            }
        
        if llm:
            prompt = f"""Current failure: {failure}
Root cause: {root_finding}

Previous similar failures:
{chr(10).join([f"- {e.content}" for e in similar_failures[:5]])}

Layer 3 - Pattern Discovery:
Is this part of a larger pattern? What connects these failures?

Provide: pattern description and evidence (specific commonalities)
"""
            result = await llm(prompt)
            # Extract pattern from result
            return {"pattern": "detected", "finding": result, "evidence": [f"Similar failures: {len(similar_failures)}"]}
        
        return {
            "pattern": "detected",
            "finding": f"Pattern: {len(similar_failures)} similar failures share common elements.",
            "evidence": [f"Found {len(similar_failures)} related failures"]
        }
    
    async def _generate_recommendation(
        self, excavation: Excavation, llm
    ) -> str:
        """Generate actionable recommendation based on excavation."""
        if llm:
            prompt = f"""Failure excavation:
{excavation.summary()}

Based on this 3-layer analysis, what specific action should be taken to:
1. Fix the immediate issue
2. Prevent the root cause
3. Break the pattern (if any)

Provide a concrete recommendation.
"""
            return await llm(prompt)
        
        return "Recommendation: Review layers above and address root cause."
    
    def quick_dig(self, failure: str) -> Excavation:
        """Quick synchronous dig without LLM."""
        excavation = Excavation(initial_failure=failure)
        excavation.add_layer(
            FailureDepth.SURFACE,
            f"Task '{failure}' failed to complete successfully.",
            ["Direct observation"]
        )
        excavation.add_layer(
            FailureDepth.ROOT,
            "Root cause unknown - LLM required for analysis.",
            ["Requires deeper investigation"]
        )
        excavation.recommendation = "Run with LLM provider for full excavation."
        return excavation
