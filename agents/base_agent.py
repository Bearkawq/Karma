"""Base Agent - Abstract agent interface for Karma's modular agent framework.

Agents are specialized workers for task roles. They are NOT personalities.
They are functional roles that Karma can invoke, load, unload, and ignore.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional
from enum import Enum


class AgentStatus(Enum):
    """Agent operational status."""
    UNLOADED = "unloaded"
    LOADING = "loading"
    READY = "ready"
    ACTIVE = "active"
    ERROR = "error"
    DISABLED = "disabled"


@dataclass
class AgentCapabilities:
    """What this agent can do."""
    can_plan: bool = False
    can_execute: bool = False
    can_retrieve: bool = False
    can_summarize: bool = False
    can_criticize: bool = False
    can_navigate: bool = False
    requires_model: bool = False
    model_role_preference: Optional[str] = None
    deterministic_fallback: bool = True
    tags: List[str] = field(default_factory=list)


@dataclass
class AgentContext:
    """Context passed to agent during execution."""
    task: str
    input_data: Any = None
    memory: Any = None
    retrieval: Any = None
    config: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentResult:
    """Result from agent execution."""
    success: bool
    output: Any = None
    error: Optional[str] = None
    artifacts: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    used_model: Optional[str] = None
    execution_time_ms: float = 0.0


class BaseAgent(ABC):
    """Abstract base class for Karma agents.
    
    Agents are functional workers, not personalities.
    Karma remains in control; agents are tools.
    """
    
    def __init__(self, agent_id: str, role_name: str):
        self.agent_id = agent_id
        self.role_name = role_name
        self._status = AgentStatus.UNLOADED
        self._capabilities = AgentCapabilities()
        self._last_error: Optional[str] = None
        self._execution_count = 0
    
    @abstractmethod
    def get_capabilities(self) -> AgentCapabilities:
        """Return what this agent can do."""
        pass
    
    @abstractmethod
    def run(self, context: AgentContext) -> AgentResult:
        """Execute the agent's task.
        
        Args:
            context: Task context with input, memory, retrieval, etc.
            
        Returns:
            AgentResult with output or error
        """
        pass
    
    @property
    def status(self) -> AgentStatus:
        """Current agent status."""
        return self._status
    
    @property
    def is_available(self) -> bool:
        """Check if agent can be used."""
        return self._status in (AgentStatus.READY, AgentStatus.ACTIVE)
    
    @property
    def last_error(self) -> Optional[str]:
        """Last error encountered."""
        return self._last_error
    
    def warmup(self) -> bool:
        """Optional warmup/initialization.
        
        Returns:
            True if warmup successful
        """
        self._status = AgentStatus.READY
        return True
    
    def shutdown(self) -> bool:
        """Optional cleanup/unload.
        
        Returns:
            True if shutdown successful
        """
        self._status = AgentStatus.UNLOADED
        return True
    
    def enable(self) -> None:
        """Enable this agent."""
        if self._status == AgentStatus.DISABLED:
            self._status = AgentStatus.READY
    
    def disable(self) -> None:
        """Disable this agent."""
        self._status = AgentStatus.DISABLED
    
    def _record_execution(self, success: bool) -> None:
        """Record execution for telemetry."""
        self._execution_count += 1
        if not success:
            self._status = AgentStatus.ERROR
    
    def get_stats(self) -> Dict[str, Any]:
        """Get agent statistics."""
        return {
            "agent_id": self.agent_id,
            "role_name": self.role_name,
            "status": self._status.value,
            "execution_count": self._execution_count,
            "last_error": self._last_error,
            "capabilities": {
                "can_plan": self._capabilities.can_plan,
                "can_execute": self._capabilities.can_execute,
                "can_retrieve": self._capabilities.can_retrieve,
                "can_summarize": self._capabilities.can_summarize,
                "can_criticize": self._capabilities.can_criticize,
                "can_navigate": self._capabilities.can_navigate,
                "requires_model": self._capabilities.requires_model,
            },
        }


    def _try_model(
        self,
        prompt: str,
        system: str = "",
        max_tokens: int = 512,
    ) -> Optional[str]:
        """Try to generate using the assigned seat model.

        Returns generated text or None if no model is available.
        Callers fall back to deterministic logic on None.
        """
        try:
            from core.agent_model_manager import get_agent_model_manager
            from core.slot_manager import get_slot_manager
        except ImportError:
            return None

        try:
            sm = get_slot_manager()
            assignment = sm.get_role_assignment(self.role_name)
            if not assignment or not assignment.assigned_model_id:
                return None

            mgr = get_agent_model_manager()
            model_id = assignment.assigned_model_id
            adapter = mgr._models.get(model_id)
            if adapter is None:
                return None

            if not adapter.is_loaded:
                if not adapter.load():
                    return None

            raw = adapter.generate(prompt, max_tokens=max_tokens, system=system)
            return _clean_model_output(raw) if raw else None
        except Exception:
            return None


def _clean_model_output(text: str) -> str:
    """Strip common reasoning preambles from model output.

    Patterns only strip from the *start* of the string; [^\n]* prevents
    DOTALL from consuming the entire document.
    """
    import re
    # Remove <think> block (may span lines)
    text = re.sub(r"^<think>.*?</think>\s*", "", text, flags=re.DOTALL)
    # Remove single-line preamble patterns at the top of the string
    preamble = re.compile(
        r"^(?:"
        r"Hmm[,.]?\s[^\n]*\n|"
        r"Let me (?:think|re-read|analyze|check|look)[^\n]*\n|"
        r"The user (?:wants|asked|is asking)[^\n]*\n|"
        r"I (?:need to|should|will|must)[^\n]*\n|"
        r"Okay[,.]?\s[^\n]*\n|"
        r"Alright[,.]?\s[^\n]*\n|"
        r"We are given (?:a task|a plan|the following)[^\n]*\n|"
        r"Let's (?:analyze|look|think|break|review)[^\n]*\n"
        r")+",
        re.IGNORECASE,
    )
    text = preamble.sub("", text)
    return text.strip()


def _extract_numbered_lines(text: str) -> str:
    """Extract first consecutive block of numbered list lines from model output."""
    import re
    blocks: list = []
    current: list = []
    in_block = False
    for line in text.splitlines():
        if re.match(r"\s*\d+[.)]\s+.+", line.strip()):
            in_block = True
            current.append(line.strip())
        else:
            if in_block and current:
                blocks.append(current[:])
                current = []
                in_block = False
    if current:
        blocks.append(current)
    # Use the largest block (most steps)
    if blocks:
        best = max(blocks, key=len)
        return "\n".join(best)
    return text


def _extract_bullet_issues(text: str) -> str:
    """Extract bullet-style issues from model output.

    Finds the section after 'Issues:' or 'Flaws:' or lines starting with
    '-' / '*' / numbered items. Falls back to full text if nothing found.
    """
    import re
    # Try to find issues section
    m = re.search(r"(?:Issues?|Flaws?|Problems?|Critique)[:\s]*\n+(.*)", text,
                  re.IGNORECASE | re.DOTALL)
    if m:
        section = m.group(1).strip()
    else:
        section = text

    # Extract bullet/numbered lines
    bullets = []
    for line in section.splitlines():
        stripped = line.strip()
        if re.match(r"[-*•]\s+|^\d+[.)]\s+", stripped):
            # Stop after 5 bullets
            if len(bullets) >= 5:
                break
            bullets.append(stripped)

    if bullets:
        return "\n".join(bullets)
    # Check for "OK" anywhere
    if re.search(r"\bOK\b", text, re.IGNORECASE):
        return "OK"
    # Last resort: first 3 sentences
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    return " ".join(sentences[:3])


class NullAgent(BaseAgent):
    """Null agent that does nothing - for disabled roles."""
    
    def __init__(self, agent_id: str = "null", role_name: str = "null"):
        super().__init__(agent_id, role_name)
        self._status = AgentStatus.DISABLED
    
    def get_capabilities(self) -> AgentCapabilities:
        return AgentCapabilities()
    
    def run(self, context: AgentContext) -> AgentResult:
        return AgentResult(
            success=False,
            error="Agent is disabled",
        )
