import json
import sys
from pathlib import Path
from typing import Optional

# Ensure project root is on sys.path so agent/core/research imports work
_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

try:
    from textual.app import App, ComposeResult
    from textual.containers import Horizontal, Vertical
    from textual.widgets import Header, Footer, Input, Static, RichLog, DataTable, Tabs, Tab
    TEXTUAL_IMPORT_ERROR = None
except Exception as e:
    class _DummyApp:
        pass
    class _DummyComposeResult:
        pass
    class _DummyWidget:
        def __init__(self, *args, **kwargs):
            pass
    class _DummyContainer:
        def __init__(self, *args, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc, tb):
            return False
    class _DummyTabs(_DummyWidget):
        class TabActivated:
            tab = None
    App = _DummyApp
    ComposeResult = _DummyComposeResult
    Horizontal = Vertical = _DummyContainer
    class _DummyInput(_DummyWidget):
        class Submitted:
            value = ""
    Header = Footer = Static = RichLog = DataTable = Tab = _DummyWidget
    Input = _DummyInput
    Tabs = _DummyTabs
    TEXTUAL_IMPORT_ERROR = e

from agent.bootstrap import load_config, build_agent, get_version
from agent.agent_loop import AgentLoop


def tail_lines(path: Path, n: int = 200) -> str:
    if not path.exists():
        return ""
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        return "".join(lines[-n:])
    except Exception:
        return ""


# Event kind -> color mapping
EVENT_COLORS = {
    "learn_start": "#6af",
    "learn_slice": "#6af",
    "learn_done": "#6af",
    "learn_error": "#f66",
    "source_fetched": "#6af",
    "note_written": "#6af",
    "branch_selected": "#6af",
    "loop_start": "#0c0",
    "executed": "#0c0",
    "intent_parsed": "#ff0",
    "scored": "#ff0",
    "reflected": "#c6f",
    "responded": "#9ad",
}


class KarmaCockpit(App):
    CSS = """
    Screen { background: #0b0b0d; }
    #main { height: 1fr; }
    #left { width: 35%; border: solid #222; }
    #center { width: 40%; border: solid #222; }
    #right { width: 25%; border: solid #222; }
    #inputbar { height: auto; border-top: solid #222; padding: 0 1; }
    .panel_title { color: #ddd; background: #121217; padding: 0 1; }
    """

    BINDINGS = [
        ("ctrl+k", "focus_input", "Command"),
        ("f1", "refresh_now", "Refresh"),
        ("f2", "toggle_auto", "Auto On/Off"),
        ("f3", "focus_thoughts", "Thoughts"),
        ("ctrl+l", "clear_console", "Clear Console"),
    ]

    def __init__(self):
        if TEXTUAL_IMPORT_ERROR is not None:
            raise RuntimeError(f"Textual is required for the cockpit UI: {TEXTUAL_IMPORT_ERROR}")
        super().__init__()
        self.root_dir = Path(__file__).resolve().parent.parent
        self.config = load_config()
        self.agent = build_agent(self.config)

        mem_cfg = self.config.get("memory", {})
        log_cfg = self.config.get("logging", {})
        self.state_file = (self.root_dir / mem_cfg.get("state_file", "data/agent_state.json")).resolve()
        self.episodic_file = (self.root_dir / mem_cfg.get("episodic_file", "data/episodic.jsonl")).resolve()
        self.log_file = (self.root_dir / log_cfg.get("log_dir", "data/logs") / "karma.log").resolve()
        self._do_auto_refresh = True
        self._active_tab = "Log"

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)

        with Horizontal(id="main"):
            with Vertical(id="left"):
                yield Static("TASKS", classes="panel_title")
                self.task_table = DataTable()
                self.task_table.add_columns("Pri", "Task", "Status")
                yield self.task_table

                yield Static("FACTS (top confidence)", classes="panel_title")
                self.facts_table = DataTable()
                self.facts_table.add_columns("Conf", "Fact")
                yield self.facts_table

            with Vertical(id="center"):
                yield Static("CONSOLE", classes="panel_title")
                self.console_log = RichLog(highlight=True, markup=True)
                yield self.console_log

                yield Static("THOUGHTS (live trace)", classes="panel_title")
                self.thoughtlog = RichLog(highlight=True, markup=True)
                yield self.thoughtlog

            with Vertical(id="right"):
                yield Static("TELEMETRY", classes="panel_title")
                self.tele_tabs = Tabs(
                    Tab("Log", id="tab-log"),
                    Tab("State", id="tab-state"),
                    Tab("Memory", id="tab-memory"),
                    Tab("Tools", id="tab-tools"),
                )
                yield self.tele_tabs
                self.telemetry = RichLog(highlight=True, markup=True)
                yield self.telemetry

        with Horizontal(id="inputbar"):
            self.input = Input(placeholder="Type command...")
            yield self.input

        yield Footer()

    def on_mount(self) -> None:
        self.set_interval(0.6, self._auto_refresh)
        self.input.focus()
        self.console_log.write("[bold #9ad]Karma Cockpit online.[/]\n")
        self.refresh_panels()

    # ── keybindings ────────────────────────────────────────────

    def action_focus_input(self) -> None:
        self.input.focus()

    def action_clear_console(self) -> None:
        self.console_log.clear()

    def action_refresh_now(self) -> None:
        self.refresh_panels()
        self.console_log.write("[#aaa]Refreshed all panels[/]")

    def action_toggle_auto(self) -> None:
        self._do_auto_refresh = not self._do_auto_refresh
        state = "ON" if self._do_auto_refresh else "OFF"
        self.console_log.write(f"[#aaa]Auto-refresh: {state}[/]")

    def action_focus_thoughts(self) -> None:
        self.thoughtlog.focus()

    # ── tab switching ──────────────────────────────────────────

    def on_tabs_tab_activated(self, event: Tabs.TabActivated) -> None:
        tab_id = event.tab.id or ""
        label = tab_id.replace("tab-", "").capitalize()
        self._active_tab = label
        self._refresh_telemetry()

    # ── auto refresh ───────────────────────────────────────────

    def _auto_refresh(self) -> None:
        if self._do_auto_refresh:
            self.refresh_panels()

    # ── refresh all ────────────────────────────────────────────

    def refresh_panels(self) -> None:
        self._refresh_thoughts()
        self._refresh_tasks()
        self._refresh_facts()
        self._refresh_telemetry()

    # ── thoughts panel ─────────────────────────────────────────

    def _refresh_thoughts(self) -> None:
        event_file = self.root_dir / "data" / "events.jsonl"
        if not event_file.exists():
            return
        try:
            lines = event_file.read_text(encoding="utf-8").splitlines()
            recent = lines[-30:]
            events = []
            for l in recent:
                try:
                    events.append(json.loads(l))
                except json.JSONDecodeError:
                    continue

            self.thoughtlog.clear()
            for e in events[-20:]:
                kind = e.get("kind", "unknown")
                data = e.get("data", {})
                ts = e.get("t", "")[-8:]
                color = EVENT_COLORS.get(kind, "#888")

                # Extract best detail string
                detail = (
                    data.get("subtopic")
                    or data.get("topic")
                    or data.get("text")
                    or data.get("url", "")
                    or ""
                )
                if isinstance(detail, dict):
                    detail = str(detail)[:60]
                else:
                    detail = str(detail)[:60]

                self.thoughtlog.write(f"[{color}]{ts} {kind}[/] {detail}")
        except Exception:
            pass

    # ── tasks panel ────────────────────────────────────────────

    def _refresh_tasks(self) -> None:
        try:
            self.task_table.clear()
            tasks = self.agent.memory.tasks
            if not tasks:
                return
            # Sort by priority (lower = higher priority)
            sorted_tasks = sorted(
                tasks.values(),
                key=lambda t: int(t.get("priority", 99)),
            )
            for t in sorted_tasks[:30]:
                pri = str(t.get("priority", "-"))
                goal = str(t.get("goal", t.get("id", "?")))[:60]
                status = str(t.get("status", "?"))
                self.task_table.add_row(pri, goal, status)
        except Exception:
            pass

    # ── facts panel ────────────────────────────────────────────

    def _refresh_facts(self) -> None:
        try:
            self.facts_table.clear()
            items = sorted(
                self.agent.memory.facts.items(),
                key=lambda kv: float(kv[1].get("confidence", 0.0)),
                reverse=True,
            )[:50]
            for k, v in items:
                conf = f"{float(v.get('confidence', 0.0)):.2f}"
                fact = str(k)[:80]
                self.facts_table.add_row(conf, fact)
        except Exception:
            pass

    # ── telemetry panel ────────────────────────────────────────

    def _refresh_telemetry(self) -> None:
        self.telemetry.clear()
        tab = self._active_tab
        try:
            if tab == "Log":
                self._tele_log()
            elif tab == "State":
                self._tele_state()
            elif tab == "Memory":
                self._tele_memory()
            elif tab == "Tools":
                self._tele_tools()
        except Exception:
            self.telemetry.write("[#f66]Error reading telemetry[/]")

    def _tele_log(self) -> None:
        text = tail_lines(self.log_file, n=40)
        if text:
            for line in text.splitlines()[-30:]:
                self.telemetry.write(line[:120])
        else:
            self.telemetry.write("[#888]No log file yet[/]")

    def _tele_state(self) -> None:
        if not self.state_file.exists():
            self.telemetry.write("[#888]No state file yet[/]")
            return
        with open(self.state_file, "r") as f:
            st = json.load(f)
        self.telemetry.write(f"[bold]Last run:[/] {st.get('last_run', 'never')}")
        self.telemetry.write(f"[bold]Current task:[/] {st.get('current_task', 'none')}")
        ds = st.get("decision_summary", {})
        self.telemetry.write(f"[bold]Decisions:[/] {ds.get('total_decisions', 0)}")
        self.telemetry.write(f"[bold]Success rate:[/] {ds.get('success_rate', 0):.1%}")
        self.telemetry.write(f"[bold]Avg confidence:[/] {ds.get('average_confidence', 0):.2f}")
        logs = st.get("execution_log", [])
        if logs:
            last = logs[-1]
            intent = last.get("intent", {}).get("intent", "?")
            success = last.get("success", False)
            self.telemetry.write(f"[bold]Last action:[/] {intent} ({'ok' if success else 'fail'})")

    def _tele_memory(self) -> None:
        try:
            stats = self.agent.memory.get_stats()
            self.telemetry.write(f"[bold]Facts:[/] {stats['facts_count']}")
            self.telemetry.write(f"[bold]Episodes:[/] {stats['episodic_count']}")
            self.telemetry.write(f"[bold]Tasks:[/] {stats['tasks_count']}")
            self.telemetry.write(f"[bold]Facts file:[/] {stats['facts_file_size'] // 1024} KB")
            self.telemetry.write(f"[bold]Episodic file:[/] {stats['episodic_file_size'] // 1024} KB")
            # Learn sessions
            learn_dir = self.root_dir / "data" / "learn"
            if learn_dir.exists():
                sessions = [d for d in learn_dir.iterdir() if d.is_dir()]
                self.telemetry.write(f"[bold]GoLearn sessions:[/] {len(sessions)}")
            # Events count
            ev_file = self.root_dir / "data" / "events.jsonl"
            if ev_file.exists():
                ev_lines = ev_file.read_text().splitlines()
                self.telemetry.write(f"[bold]Events:[/] {len(ev_lines)}")
        except Exception:
            self.telemetry.write("[#f66]Error reading memory stats[/]")

    def _tele_tools(self) -> None:
        enabled = self.config.get("tools", {}).get("enabled", [])
        self.telemetry.write("[bold]Enabled tools:[/]")
        for t in enabled:
            self.telemetry.write(f"  [#0c0]{t}[/]")
        # Show registered tools
        registered = self.agent.tool_manager.list_tools()
        if registered:
            self.telemetry.write(f"\n[bold]Registered:[/] {len(registered)}")
            for tool in registered[:10]:
                name = tool if isinstance(tool, str) else tool.get("name", "?")
                self.telemetry.write(f"  {name}")

    # ── input handling ─────────────────────────────────────────

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if not text:
            return
        self.input.value = ""

        self.console_log.write(f"[bold #fff]>[/] {text}")
        self.thoughtlog.write(f"[#9ad]observe[/] user_input={text!r}")

        import threading

        def _bg():
            try:
                result = self.agent.run(text)
                for line in result.splitlines():
                    self.call_from_thread(self.console_log.write, f"[#9ad]{line}[/]")
            except Exception as e:
                self.call_from_thread(self.console_log.write, f"[bold red]ERROR[/] {e}")
            self.call_from_thread(self.refresh_panels)

        threading.Thread(target=_bg, daemon=True).start()


def run_cockpit():
    KarmaCockpit().run()


if __name__ == "__main__":
    run_cockpit()
