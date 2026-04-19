#!/usr/bin/env python3
"""
NEXUS-C: Complete AI Agent
Combines Claude Code functionality with NEXUS multi-voice deliberation.

Input → I-Position Deliberation (4 voices) → Tool Selection → Execution → Response
Uses Ollama (qwen2.5:7b) as LLM brain.
"""

import asyncio
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional
import uuid

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.progress import Progress, SpinnerColumn, TextColumn
    from rich.table import Table
    from rich.syntax import Syntax
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False
    Console = None
    Panel = None
    Progress = None
    Table = None
    Syntax = None

# Add NEXUS to path for imports
NEXUS_PATH = Path("/home/mikoleye/work/nexus")
sys.path.insert(0, str(NEXUS_PATH))

# ============== IMPORTS FROM NEXUS ==============
from core import NexusCore, IPosition, IPositionType, VoiceContribution, Decision
from deliberation import DeliberationChamber, DecisionScope
from memory import TemporalIntensityMemory
from archaeology import FailureArchaeologist, FailureDepth
from budget import BoundedAutonomySystem, DecisionScope as BudgetScope

# ============== CONFIGURATION ==============
OLLAMA_MODEL = "qwen2.5:7b"
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
MAX_CONTEXT = 8192
TOOL_TIMEOUT = 300
OLLAMA_TIMEOUT = int(os.environ.get("NEXUS_C_OLLAMA_TIMEOUT", "10"))

# ============== DATA CLASSES ==============
@dataclass
class ToolResult:
    """Result of tool execution."""
    tool: str
    success: bool
    output: str = ""
    error: str = ""
    duration: float = 0.0

@dataclass
class Message:
    """A message in the conversation."""
    role: str  # user, assistant, system
    content: str
    tool_calls: list[dict] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)

@dataclass
class ExecutionContext:
    """Context for tool execution."""
    session_id: str
    working_dir: str = os.getcwd()
    env: dict = field(default_factory=dict)
    plan_mode: bool = False
    notebook_path: str = field(default_factory=lambda: str(Path(os.getcwd()) / "nexus_notes.md"))

# ============== TOOL REGISTRY ==============
class Tool:
    """Base class for all tools."""
    name: str = ""
    description: str = ""
    parameters: dict = field(default_factory=dict)
    
    def execute(self, params: dict, context: ExecutionContext) -> ToolResult:
        raise NotImplementedError

class BashTool(Tool):
    """Execute bash commands."""
    name = "Bash"
    description = "Execute shell commands"
    parameters = {
        "command": {"type": "string", "required": True},
        "description": {"type": "string", "required": False},
        "timeout": {"type": "integer", "default": 60}
    }
    
    def execute(self, params: dict, context: ExecutionContext) -> ToolResult:
        cmd = params.get("command", "")
        timeout = params.get("timeout", 60)
        
        start = time.time()
        try:
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True,
                timeout=timeout, cwd=context.working_dir
            )
            duration = time.time() - start
            return ToolResult(
                tool=self.name,
                success=result.returncode == 0,
                output=result.stdout,
                error=result.stderr if result.returncode != 0 else "",
                duration=duration
            )
        except subprocess.TimeoutExpired:
            return ToolResult(tool=self.name, success=False, error="Command timed out", duration=timeout)
        except Exception as e:
            return ToolResult(tool=self.name, success=False, error=str(e), duration=time.time() - start)

class ReadTool(Tool):
    """Read file contents."""
    name = "Read"
    description = "Read file contents"
    parameters = {
        "file_path": {"type": "string", "required": True},
        "limit": {"type": "integer", "default": 1000},
        "offset": {"type": "integer", "default": 0}
    }
    
    def execute(self, params: dict, context: ExecutionContext) -> ToolResult:
        path = params.get("file_path", "")
        limit = params.get("limit", 1000)
        offset = params.get("offset", 0)
        
        try:
            with open(path, 'r') as f:
                f.seek(offset)
                content = f.read(limit)
            return ToolResult(tool=self.name, success=True, output=content)
        except FileNotFoundError:
            return ToolResult(tool=self.name, success=False, error=f"File not found: {path}")
        except Exception as e:
            return ToolResult(tool=self.name, success=False, error=str(e))

class WriteTool(Tool):
    """Write content to file."""
    name = "Write"
    description = "Write content to file"
    parameters = {
        "file_path": {"type": "string", "required": True},
        "content": {"type": "string", "required": True}
    }
    
    def execute(self, params: dict, context: ExecutionContext) -> ToolResult:
        path = params.get("file_path", "")
        content = params.get("content", "")
        
        try:
            with open(path, 'w') as f:
                f.write(content)
            return ToolResult(tool=self.name, success=True, output=f"Wrote {len(content)} bytes to {path}")
        except Exception as e:
            return ToolResult(tool=self.name, success=False, error=str(e))

class EditTool(Tool):
    """Edit a file using replacement."""
    name = "Edit"
    description = "Edit file content"
    parameters = {
        "file_path": {"type": "string", "required": True},
        "old_string": {"type": "string", "required": True},
        "new_string": {"type": "string", "required": True}
    }
    
    def execute(self, params: dict, context: ExecutionContext) -> ToolResult:
        path = params.get("file_path", "")
        old = params.get("old_string", "")
        new = params.get("new_string", "")
        
        try:
            with open(path, 'r') as f:
                content = f.read()
            
            if old not in content:
                return ToolResult(tool=self.name, success=False, error="String not found in file")
            
            new_content = content.replace(old, new)
            
            with open(path, 'w') as f:
                f.write(new_content)
            
            return ToolResult(tool=self.name, success=True, output=f"Edited {path}")
        except Exception as e:
            return ToolResult(tool=self.name, success=False, error=str(e))

class GlobTool(Tool):
    """Glob file patterns."""
    name = "Glob"
    description = "Find files matching pattern"
    parameters = {
        "pattern": {"type": "string", "required": True},
        "path": {"type": "string", "default": "."}
    }
    
    def execute(self, params: dict, context: ExecutionContext) -> ToolResult:
        pattern = params.get("pattern", "*")
        base_path = params.get("path", context.working_dir)
        
        try:
            p = Path(base_path)
            files = [str(f) for f in p.glob(pattern)]
            return ToolResult(tool=self.name, success=True, output="\n".join(files))
        except Exception as e:
            return ToolResult(tool=self.name, success=False, error=str(e))

class GrepTool(Tool):
    """Search file contents."""
    name = "Grep"
    description = "Search for pattern in files"
    parameters = {
        "pattern": {"type": "string", "required": True},
        "path": {"type": "string", "default": "."},
        "include": {"type": "string", "default": "*"}
    }
    
    def execute(self, params: dict, context: ExecutionContext) -> ToolResult:
        pattern = params.get("pattern", "")
        base_path = params.get("path", ".")
        
        try:
            result = subprocess.run(
                f"grep -r '{pattern}' {base_path} --include='*.py' --include='*.ts' --include='*.js' 2>/dev/null | head -50",
                shell=True, capture_output=True, text=True, timeout=30
            )
            return ToolResult(
                tool=self.name,
                success=result.returncode == 0,
                output=result.stdout or "No matches found",
                error=result.stderr if result.returncode != 0 else ""
            )
        except Exception as e:
            return ToolResult(tool=self.name, success=False, error=str(e))

class TaskTool(Tool):
    """Create/manage tasks."""
    name = "Task"
    description = "Create and manage tasks"
    parameters = {
        "action": {"type": "string", "required": True},  # create, list, kill
        "task_id": {"type": "string", "required": False},
        "command": {"type": "string", "required": False}
    }
    
    def execute(self, params: dict, context: ExecutionContext) -> ToolResult:
        action = params.get("action", "list")
        
        if action == "list":
            return ToolResult(tool=self.name, success=True, output="Task management available")
        elif action == "create":
            return ToolResult(tool=self.name, success=True, output=f"Task created: {params.get('command', '')}")
        return ToolResult(tool=self.name, success=False, error="Unknown action")

class SleepTool(Tool):
    """Sleep for specified duration."""
    name = "Sleep"
    description = "Wait for specified seconds"
    parameters = {
        "seconds": {"type": "number", "required": True}
    }
    
    def execute(self, params: dict, context: ExecutionContext) -> ToolResult:
        seconds = params.get("seconds", 1)
        time.sleep(seconds)
        return ToolResult(tool=self.name, success=True, output=f"Slept for {seconds} seconds")

class WebSearchTool(Tool):
    """Search the web."""
    name = "WebSearch"
    description = "Search the web for information"
    parameters = {
        "query": {"type": "string", "required": True}
    }
    
    def execute(self, params: dict, context: ExecutionContext) -> ToolResult:
        query = params.get("query", "")
        try:
            result = subprocess.run(
                f"ddg '{query}' 2>/dev/null | head -20",
                shell=True, capture_output=True, text=True, timeout=10
            )
            return ToolResult(tool=self.name, success=True, output=result.stdout or "No results")
        except Exception as e:
            return ToolResult(tool=self.name, success=False, error=str(e))

class ConfigTool(Tool):
    """Get/set configuration."""
    name = "Config"
    description = "Get or set configuration values"
    parameters = {
        "action": {"type": "string", "required": True},  # get, set
        "key": {"type": "string", "required": False},
        "value": {"type": "string", "required": False}
    }
    
    def execute(self, params: dict, context: ExecutionContext) -> ToolResult:
        action = params.get("action", "get")
        if action == "get":
            key = params.get("key")
            if key:
                value = getattr(context, key, context.env.get(key))
                return ToolResult(tool=self.name, success=True, output=f"{key}={value}")
            return ToolResult(
                tool=self.name,
                success=True,
                output=json.dumps(
                    {
                        "working_dir": context.working_dir,
                        "plan_mode": context.plan_mode,
                        "notebook_path": context.notebook_path,
                    },
                    indent=2,
                ),
            )
        if action == "set":
            key = params.get("key")
            value = params.get("value")
            if not key:
                return ToolResult(tool=self.name, success=False, error="Missing config key")
            if hasattr(context, key):
                setattr(context, key, value)
            else:
                context.env[key] = value
            return ToolResult(tool=self.name, success=True, output=f"Config updated: {key}={value}")
        return ToolResult(tool=self.name, success=False, error="Unsupported config action")

class EnterPlanModeTool(Tool):
    """Enter plan mode."""
    name = "EnterPlanMode"
    description = "Enter planning mode for complex tasks"
    parameters = {}
    
    def execute(self, params: dict, context: ExecutionContext) -> ToolResult:
        context.plan_mode = True
        return ToolResult(tool=self.name, success=True, output="Entered plan mode")

class ExitPlanModeTool(Tool):
    """Exit plan mode."""
    name = "ExitPlanMode"
    description = "Exit planning mode"
    parameters = {}
    
    def execute(self, params: dict, context: ExecutionContext) -> ToolResult:
        context.plan_mode = False
        return ToolResult(tool=self.name, success=True, output="Exited plan mode")

class NotebookEditTool(Tool):
    """Append notes to a notebook-like file."""
    name = "NotebookEdit"
    description = "Edit Jupyter notebook cells"
    parameters = {
        "file_path": {"type": "string", "required": True},
        "content": {"type": "string", "required": False}
    }
    
    def execute(self, params: dict, context: ExecutionContext) -> ToolResult:
        file_path = params.get("file_path") or context.notebook_path
        content = params.get("content", "")
        try:
            with open(file_path, "a") as f:
                f.write(content.rstrip() + "\n")
            return ToolResult(tool=self.name, success=True, output=f"Appended note to {file_path}")
        except Exception as e:
            return ToolResult(tool=self.name, success=False, error=str(e))

class SendMessageTool(Tool):
    """Queue a message for another agent or human."""
    name = "SendMessage"
    description = "Send a message to another agent or user"
    parameters = {
        "target": {"type": "string", "required": True},
        "message": {"type": "string", "required": True},
    }

    def execute(self, params: dict, context: ExecutionContext) -> ToolResult:
        target = params.get("target", "unknown")
        message = params.get("message", "")
        return ToolResult(tool=self.name, success=True, output=f"Queued message for {target}: {message}")

class RemoteTriggerTool(Tool):
    """Record a remote trigger request."""
    name = "RemoteTrigger"
    description = "Stage a remote trigger action"
    parameters = {
        "target": {"type": "string", "required": True},
        "action": {"type": "string", "required": True},
    }

    def execute(self, params: dict, context: ExecutionContext) -> ToolResult:
        return ToolResult(
            tool=self.name,
            success=True,
            output=f"Remote trigger staged for {params.get('target')}: {params.get('action')}"
        )

# ============== TOOL REGISTRY ==============
class ToolRegistry:
    """Registry of all available tools."""
    
    def __init__(self):
        self.tools: dict[str, Tool] = {}
        self._register_defaults()
    
    def _register_defaults(self):
        """Register default tools."""
        self.register(BashTool())
        self.register(ReadTool())
        self.register(WriteTool())
        self.register(EditTool())
        self.register(GlobTool())
        self.register(GrepTool())
        self.register(TaskTool())
        self.register(SleepTool())
        self.register(WebSearchTool())
        self.register(ConfigTool())
        self.register(EnterPlanModeTool())
        self.register(ExitPlanModeTool())
        self.register(SendMessageTool())
        self.register(RemoteTriggerTool())
        self.register(NotebookEditTool())
    
    def register(self, tool: Tool):
        """Register a tool."""
        self.tools[tool.name] = tool
    
    def get(self, name: str) -> Optional[Tool]:
        """Get a tool by name."""
        return self.tools.get(name)
    
    def list_tools(self) -> list[dict]:
        """List all available tools."""
        return [
            {"name": t.name, "description": t.description, "parameters": t.parameters}
            for t in self.tools.values()
        ]

# ============== OLLAMA CONNECTOR ==============
class OllamaConnector:
    """Connector to Ollama LLM."""
    
    def __init__(self, model: str = OLLAMA_MODEL, timeout: int = OLLAMA_TIMEOUT):
        self.model = model
        self.timeout = timeout
        self._current_proc = None
    
    async def generate(self, prompt: str, system_prompt: str = "", 
                      tools: list[dict] = None) -> str:
        """Generate response from Ollama with timeout."""
        
        # Build the full prompt with system and tools
        full_prompt = self._build_prompt(prompt, system_prompt, tools or [])
        
        try:
            # Use asyncio subprocess for timeout control
            self._current_proc = await asyncio.create_subprocess_exec(
                "ollama", "run", self.model,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                stdin=asyncio.subprocess.PIPE
            )
            
            try:
                stdout, stderr = await asyncio.wait_for(
                    self._current_proc.communicate(full_prompt.encode()),
                    timeout=self.timeout
                )
                output = stdout.decode() or stderr.decode()
                # Strip ANSI codes
                output = re.sub(r'\x1b\[[0-9;]*[JK]', '', output)
                output = re.sub(r'\x1b\?', '', output)
                return output.strip()
            except asyncio.TimeoutError:
                try:
                    self._current_proc.kill()
                except:
                    pass
                try:
                    await asyncio.wait_for(self._current_proc.wait(), timeout=1.0)
                except:
                    pass
                return f"[Timeout after {self.timeout}s - Ollama response delayed]"
            finally:
                if self._current_proc:
                    try:
                        self._current_proc.terminate()
                    except:
                        pass
                    self._current_proc = None
                
        except Exception as e:
            return f"Error: {str(e)}"
    
    def _build_prompt(self, prompt: str, system: str, tools: list[dict]) -> str:
        """Build the full prompt with tools."""
        full = f"{system}\n\n" if system else ""
        full += f"User: {prompt}\n\n"
        
        if tools:
            full += "Available tools:\n"
            for t in tools:
                full += f"- {t['name']}: {t['description']}\n"
            full += "\n"
        
        full += (
            "Assistant: respond with an actionable plan. "
            "Name any tool you want to use and the exact target.\n"
        )
        return full[:2000]  # Limit prompt length

# ============== NEXUS-C CORE ==============
class NexusC:
    """Main NEXUS-C Agent."""
    
    def __init__(self, model: str = OLLAMA_MODEL):
        # NEXUS components
        self.core = NexusCore()
        self.deliberation = DeliberationChamber(self.core)
        self.memory = TemporalIntensityMemory()
        self.archaeologist = FailureArchaeologist(self.memory)
        self.budget = BoundedAutonomySystem(self.core.list_voices())
        
        # NEXUS-C components
        self.tools = ToolRegistry()
        self.ollama = OllamaConnector(model)
        self.console = Console() if Console else None
        
        # Session
        self.session_id = str(uuid.uuid4())[:8]
        self.messages: list[Message] = []
        self.context = ExecutionContext(session_id=self.session_id)
        self._ollama_proc = None
        
        # Setup LLM provider in deliberation
        self._setup_llm()
    
    async def cleanup(self):
        """Clean up resources on exit."""
        if self.ollama._current_proc:
            try:
                self.ollama._current_proc.terminate()
                await asyncio.wait_for(self.ollama._current_proc.wait(), timeout=1.0)
            except:
                pass
    
    def _setup_llm(self):
        """Setup Ollama as LLM provider for deliberation."""
        async def ollama_provider(prompt: str) -> str:
            return await self.ollama.generate(prompt)
        
        self.deliberation.set_llm_provider(ollama_provider)

    def _log(self, message: str):
        """Simple logger - just prints to console."""
        print(message)

    def _voice_name(self, voice: Any) -> str:
        return getattr(voice, "name", str(voice))

    def _display_block(self, title: str, body: str):
        """Simple display without fancy UI."""
        print(f"\n=== {body} ===")

    async def _deliberate_with_timeout(self, task: str):
        async def _run():
            return await self.deliberation.deliberate(task)

        try:
            if self.console and Progress and SpinnerColumn and TextColumn:
                with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=self.console) as progress:
                    progress.add_task(description="Deliberating", total=None)
                    return await asyncio.wait_for(_run(), timeout=self.ollama.timeout)
            return await asyncio.wait_for(_run(), timeout=self.ollama.timeout)
        except asyncio.TimeoutError:
            return self._fallback_deliberation(task, f"Deliberation timed out after {self.ollama.timeout}s")
        except Exception as e:
            return self._fallback_deliberation(task, f"Deliberation error: {e}")

    def _fallback_deliberation(self, task: str, reason: str):
        from deliberation import DeliberationResult

        contributions = [
            VoiceContribution(
                voice=voice,
                position=f"{self._voice_name(voice)} fallback: use direct tool heuristics for '{task}'",
                reasoning=reason,
                confidence=0.35,
                timestamp=time.time(),
                vote="fallback",
            )
            for voice in self.core.voices
        ]

        decision = Decision(
            id=str(uuid.uuid4())[:8],
            task=task,
            decision_type="fallback",
            choices_considered=["keyword_heuristics", "manual_response"],
            chosen_path=f"{reason}. Proceed with direct tool selection when possible.",
            votes={self._voice_name(c.voice): c.vote or "fallback" for c in contributions},
            dissent_recorded=[],
            confidence=0.35,
            requires_human=False,
            timestamp=time.time(),
            outcome=None,
        )

        return DeliberationResult(
            decision=decision,
            contributions=contributions,
            debate_log=[reason],
            overseer_intervention=reason,
        )

    def _extract_first_path(self, text: str) -> Optional[str]:
        for token in text.split():
            candidate = token.strip("\"'`,.;:()[]{}")
            if candidate.startswith(("/", "./", "../", "~/")):
                return os.path.expanduser(candidate)
        return None

    def _extract_command(self, text: str) -> Optional[str]:
        match = re.search(r"(?:run|execute|bash|shell|command|cmd)\s+(.+)", text, re.IGNORECASE)
        return match.group(1).strip() if match else None

    def _plan_tool_execution(self, task: str, decision: str) -> list[dict]:
        combined = f"{task}\n{decision}"
        lowered = combined.lower()
        plans: list[dict] = []

        command = self._extract_command(task) or self._extract_command(decision)
        file_path = self._extract_first_path(task) or self._extract_first_path(decision)

        if command:
            plans.append({"tool": "Bash", "params": {"command": command, "timeout": 30}})
        elif any(kw in lowered for kw in ["list", "ls", "dir", "glob", "find files"]):
            plans.append({"tool": "Glob", "params": {"pattern": "*", "path": self.context.working_dir}})

        if any(kw in lowered for kw in ["read", "open", "show", "cat"]):
            target = file_path or str(Path(self.context.working_dir) / "README.md")
            plans.append({"tool": "Read", "params": {"file_path": target, "limit": 1200}})

        grep_match = re.search(r"(?:search|grep|find in|look for)\s+['\"]?([^'\"]+)['\"]?", combined, re.IGNORECASE)
        if grep_match:
            plans.append({"tool": "Grep", "params": {"pattern": grep_match.group(1).strip(), "path": self.context.working_dir}})

        seen = set()
        unique = []
        for plan in plans:
            key = (plan["tool"], json.dumps(plan["params"], sort_keys=True))
            if key in seen:
                continue
            seen.add(key)
            unique.append(plan)
        return unique
    
    async def think(self, task: str, use_llm: bool = False) -> dict:
        """Process a task through NEXUS-C deliberation.
        
        Args:
            task: The task to process
            use_llm: If True, use Ollama for deliberation (slow). If False, skip LLM (fast).
        """
        self._display_block("NEXUS-C Thinking", task)
        
        # Fast path: skip deliberation for simple auto-detected tasks
        simple_tools = {
            "status": ("Glob", {"pattern": "*"}),
            "status check": ("Glob", {"pattern": "*"}),
            "check status": ("Glob", {"pattern": "*"}),
            "list files": ("Glob", {"pattern": "*"}),
            "list files in this folder": ("Glob", {"pattern": "*"}),
            "list": ("Glob", {"pattern": "*"}),
            "show files": ("Glob", {"pattern": "*"}),
            "tools": ("Glob", {"pattern": "*.py"}),
        }
        
        # Check for conversational inputs (greetings, questions, etc.)
        conversational = {
            "hello": "Hello! I'm NEXUS-C. I can help you with tasks like listing files, reading files, running commands, or answering questions. What would you like me to do?",
            "hi": "Hi there! I'm NEXUS-C. What can I help you with?",
            "hey": "Hey! Ready to help. What do you need?",
            "how are you": "I'm doing great! Always ready to assist.",
            "who are you": "I'm NEXUS-C, an AI agent with multi-voice deliberation. I can help with file operations, running commands, and answering questions.",
            "what are you": "I'm NEXUS-C - an AI agent with 4 thinking voices (Architect, Builder, Sentinel, Provocateur). I use Ollama for brain power.",
            "help": "I can help with: listing files (list files), reading files (read [path]), running commands (run [command]), searching (grep), and general questions. Just ask!",
            "what can you do": "I can: list files, read/write/edit files, run bash commands, grep searches, web search, and chat with you. Just tell me what you need!",
        }
        
        task_lower = task.lower().strip()
        
        # Check conversational responses first
        if task_lower in conversational:
            return {
                "decision": conversational[task_lower],
                "contributions": [],
                "tool_results": []
            }
        
        # Check simple tools
        if task_lower in simple_tools:
            tool_name, params = simple_tools[task_lower]
            tool_result = await self.execute_tool(tool_name, params)
            return {
                "decision": "Done",
                "contributions": [],
                "tool_results": [{
                    "tool": tool_name,
                    "success": tool_result.success,
                    "output": tool_result.output,
                    "error": tool_result.error
                }]
            }
        
        # Classify decision scope
        scope = self.budget.classify_decision(task)
        
        # Check budget - skip showing internal details
        voices = self.core.list_voices()
        can_approve, msg = self.budget.check_approval(scope, voices, human_available=True)
        
        # Deliberate
        result = await self._deliberate_with_timeout(task)
        
        # Simple, human-readable output
        if result.contributions:
            self._log(f"Analyzed by {len(result.contributions)} voices")
        
        tool_plan = self._plan_tool_execution(task, result.decision.chosen_path)
        tool_results = []
        for plan in tool_plan[:2]:
            tool_results.append(await self.execute_tool(plan["tool"], plan["params"]))

        # Record in memory
        self.memory.add(
            content=task,
            context=result.decision.chosen_path,
            outcome="success" if result.decision.confidence > 0.5 else "pending",
            emotional_intensity=result.decision.confidence,
            tags=["deliberation", scope.value]
        )
        
        return {
            "task": task,
            "scope": scope.value,
            "decision": result.decision.chosen_path,
            "confidence": result.decision.confidence,
            "requires_human": result.decision.requires_human,
            "votes": {self._voice_name(c.voice): c.position for c in result.contributions},
            "tool_plan": tool_plan,
            "tool_results": [
                {
                    "tool": tool_result.tool,
                    "success": tool_result.success,
                    "output": tool_result.output,
                    "error": tool_result.error,
                }
                for tool_result in tool_results
            ],
        }
    
    async def execute_tool(self, tool_name: str, params: dict) -> ToolResult:
        """Execute a tool."""
        tool = self.tools.get(tool_name)
        if not tool:
            return ToolResult(tool=tool_name, success=False, error=f"Tool not found: {tool_name}")
        
        self._log(f"→ Running {tool_name}...")
        try:
            result = tool.execute(params, self.context)
        except Exception as e:
            result = ToolResult(tool=tool_name, success=False, error=f"Unhandled tool exception: {e}")
        
        # Record to memory
        self.memory.add(
            content=f"{tool_name}: {params}",
            context=result.output if result.success else result.error,
            outcome="success" if result.success else "failure",
            emotional_intensity=1.0 if result.success else 0.9,
            tags=["tool", tool_name]
        )
        
        # If failure, run archaeology
        if not result.success:
            self._log(f"\n[Running Failure Archaeology]")
            exc = await self.archaeologist.excavate(
                f"Tool {tool_name} failed: {result.error}"
            )
            self._log(exc.summary())
        
        return result
    
    async def run(self, prompt: str) -> str:
        """Main run loop: think → execute → respond."""
        result = await self.think(prompt)
        tool_results = result.get("tool_results", [])
        
        response = result.get("decision", "Done")
        
        if tool_results:
            lines = []
            for tr in tool_results:
                tool = tr.get("tool", "Unknown")
                if tr.get("success"):
                    output = tr.get("output", "").strip()
                    if output:
                        lines.append(f"• {output}")
                    else:
                        lines.append(f"• {tool} completed")
                else:
                    error = tr.get("error", "Unknown error")
                    lines.append(f"• {tool} failed: {error}")
            
            if lines:
                response += "\n\n" + "\n".join(lines)
        
        return response
    
    def status(self) -> str:
        """Get agent status."""
        return f"""NEXUS-C Status
============
Session: {self.session_id}
Model: {self.ollama.model}
Tools: {len(self.tools.tools)}
Memory: {self.memory.summary()}
Budget: {self.budget.summary()}"""

    async def interactive_chat(self):
        """Start an interactive chat session."""
        self._display_block("NEXUS-C Interactive", "Type a task, 'status', 'tools', or 'exit'.")
        while True:
            try:
                prompt = input("nexus-c> ").strip()
            except EOFError:
                break
            if not prompt:
                continue
            if prompt.lower() in {"exit", "quit"}:
                break
            if prompt.lower() == "status":
                self._log(self.status())
                continue
            if prompt.lower() == "tools":
                for t in self.tools.list_tools():
                    self._log(f"  {t['name']}: {t['description']}")
                continue
            self._log(await self.run(prompt))

# ============== CLI ==============
async def interactive_mode(agent: NexusC):
    """Interactive chat mode."""
    print("\n" + "="*50)
    print("NEXUS-C Interactive Mode")
    print("="*50)
    print("Type 'quit' or 'exit' to end session\n")
    
    try:
        while True:
            try:
                prompt = input("\n➤ ")
                if prompt.lower() in ['quit', 'exit', 'q']:
                    print("\nGoodbye!")
                    break
                
                if not prompt.strip():
                    continue
                
                # Process the prompt
                result = await agent.run(prompt)
                print(f"\n{result[:500]}")
                
            except KeyboardInterrupt:
                print("\n\nGoodbye!")
                break
            except EOFError:
                break
    finally:
        await agent.cleanup()

async def main():
    """CLI entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="NEXUS-C Agent")
    parser.add_argument("command", nargs="?", default="status")
    parser.add_argument("task", nargs="?", help="Task to process")
    parser.add_argument("--model", default=OLLAMA_MODEL, help="Ollama model")
    parser.add_argument("-i", "--interactive", action="store_true", help="Interactive mode")
    
    args = parser.parse_args()
    
    agent = NexusC(model=args.model)
    
    try:
        if args.interactive:
            await interactive_mode(agent)
        elif args.command == "status":
            print(agent.status())
        
        elif args.command == "think" and args.task:
            result = await agent.run(args.task)
            print(f"\n{result}")
        
        elif args.command == "tools":
            for t in agent.tools.list_tools():
                print(f"  {t['name']}: {t['description']}")
        
        else:
            print("Commands:")
            print("  nexus_c status                    - Show status")
            print("  nexus_c think \"task\"              - Process task")
            print("  nexus_c tools                     - List tools")
            print("  nexus_c -i                        - Interactive mode")
    finally:
        await agent.cleanup()
        await agent.ollama.cleanup() if hasattr(agent.ollama, 'cleanup') else None

if __name__ == "__main__":
    asyncio.run(main())
