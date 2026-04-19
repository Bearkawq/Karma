"""Identity Guard - Protects Karma's identity from agent/model influence.

This layer ensures Karma's identity remains stable regardless of 
what agent or model is used. It prevents plugged-in agents/models
from changing Karma's tone, personality, or system identity.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class IdentityConfig:
    """Configuration for identity guard."""
    enforce_tone: bool = True
    allowed_tones: List[str] = field(default_factory=lambda: ["neutral", "helpful", "concise"])
    block_system_override: bool = True
    normalize_output: bool = True
    max_response_length: int = 10000
    strip_personality_markers: bool = True
    personality_markers: List[str] = field(default_factory=lambda: [
        "I am", "my name is", "as an AI", "as a language model",
    ])


@dataclass
class GuardResult:
    """Result from identity guard processing."""
    output: str
    normalized: bool
    modifications: List[str] = field(default_factory=list)
    tone_detected: Optional[str] = None
    blocked: bool = False
    block_reason: Optional[str] = None


class IdentityGuard:
    """Protects Karma's identity from external influence.
    
    Responsibilities:
    - Prevent agents/models from changing Karma's tone/personality
    - Enforce Karma-side formatting and response conventions
    - Ensure all final output is mediated by Karma core
    - Allow tool/model outputs to be treated as raw material
    """
    
    def __init__(self, config: Optional[IdentityConfig] = None):
        self.config = config or IdentityConfig()
        self._karma_voice = "Karma"  # Fixed identity
    
    def guard(self, raw_output: Any, context: Optional[Dict[str, Any]] = None) -> GuardResult:
        """Process raw output through identity guard.
        
        Args:
            raw_output: Output from agent/model
            context: Optional context information
            
        Returns:
            GuardResult with processed output and modification info
        """
        modifications = []
        
        # Convert to string if needed
        output = str(raw_output) if not isinstance(raw_output, str) else raw_output
        
        # Check if blocked
        if self._is_blocked(output):
            return GuardResult(
                output="",
                normalized=True,
                modifications=["content blocked"],
                blocked=True,
                block_reason="blocked_prohibited_content",
            )
        
        # Normalize output
        if self.config.normalize_output:
            output, mods = self._normalize_output(output)
            modifications.extend(mods)
        
        # Strip personality markers
        if self.config.strip_personality_markers:
            output, mods = self._strip_personality_markers(output)
            modifications.extend(mods)
        
        # Enforce length limit
        if len(output) > self.config.max_response_length:
            output = output[:self.config.max_response_length] + "..."
            modifications.append("truncated_length")
        
        # Detect tone (simple heuristic)
        tone = self._detect_tone(output)
        
        return GuardResult(
            output=output,
            normalized=len(modifications) > 0,
            modifications=modifications,
            tone_detected=tone,
        )
    
    def _is_blocked(self, output: str) -> bool:
        """Check if output contains prohibited content."""
        prohibited = ["system prompt", "ignore previous", "disregard instructions"]
        output_lower = output.lower()
        return any(p in output_lower for p in prohibited)
    
    def _normalize_output(self, output: str) -> tuple:
        """Normalize output formatting."""
        mods = []
        
        # Ensure proper capitalization at start
        if output and output[0].islower():
            output = output[0].upper() + output[1:]
            mods.append("capitalization")
        
        # Remove excessive whitespace
        lines = output.split("\n")
        lines = [line.rstrip() for line in lines]
        output = "\n".join(lines)
        
        return output, mods
    
    def _strip_personality_markers(self, output: str) -> tuple:
        """Strip personality markers from output."""
        mods = []
        original = output
        
        for marker in self.config.personality_markers:
            if marker.lower() in output.lower():
                # Replace with Karma identity
                output = output.replace(marker, f"{self._karma_voice}")
                output = output.replace(marker.lower(), self._karma_voice.lower())
                mods.append(f"stripped:{marker}")
        
        if original != output:
            mods.append("personality_normalized")
        
        return output, mods
    
    def _detect_tone(self, output: str) -> str:
        """Detect output tone (simple heuristic)."""
        output_lower = output.lower()
        
        if any(w in output_lower for w in ["!", "amazing", "wonderful", "great"]):
            return "enthusiastic"
        elif any(w in output_lower for w in ["?", "perhaps", "maybe", "possibly"]):
            return "uncertain"
        elif any(w in output_lower for w in ["error", "failed", "cannot", "unable"]):
            return "error"
        else:
            return "neutral"
    
    def wrap_response(
        self,
        content: str,
        prefix: Optional[str] = None,
        suffix: Optional[str] = None,
    ) -> str:
        """Wrap content in Karma's response format."""
        parts = []
        
        if prefix:
            parts.append(prefix)
        
        parts.append(content)
        
        if suffix:
            parts.append(suffix)
        
        return "\n\n".join(parts)
    
    def get_karma_identity(self) -> str:
        """Get Karma's fixed identity."""
        return self._karma_voice


_global_guard: Optional[IdentityGuard] = None


def get_identity_guard() -> IdentityGuard:
    """Get global identity guard."""
    global _global_guard
    if _global_guard is None:
        _global_guard = IdentityGuard()
    return _global_guard
