"""
NEXUS - Main CLI and Orchestrator

Integrates all components into a cohesive system.
"""

import asyncio
import sys
from pathlib import Path

# Add nexus to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core import NexusCore
from deliberation import DeliberationChamber, DecisionScope
from memory import TemporalIntensityMemory
from archaeology import FailureArchaeologist
from budget import BoundedAutonomySystem


class Nexus:
    """Main NEXUS orchestrator."""

    def __init__(self, model: str = "qwen2.5:7b"):
        self.core = NexusCore()
        self.deliberation = DeliberationChamber(self.core)
        self.memory = TemporalIntensityMemory()
        self.archaeologist = FailureArchaeologist(self.memory)
        self.budget = BoundedAutonomySystem(self.core.list_voices())
        self.model = model
        self._setup_llm()

    def _setup_llm(self):
        """Setup Ollama as LLM provider."""
        try:
            import subprocess

            async def ollama_provider(prompt: str) -> str:
                result = subprocess.run(
                    ["ollama", "run", self.model, prompt],
                    capture_output=True,
                    text=True,
                    timeout=120
                )
                return result.stdout or result.stderr

            self.deliberation.set_llm_provider(ollama_provider)
        except Exception as e:
            print(f"Note: Ollama not available - {e}")
            print("Running in fallback mode without LLM")

    async def think(self, task: str) -> dict:
        """Process a task through NEXUS deliberation."""
        print(f"\n{'='*60}")
        print(f"NEXUS Thinking: {task}")
        print(f"{'='*60}")

        # Classify scope
        scope = self.budget.classify_decision(task)
        print(f"Decision scope: {scope.value}")

        # Check budget
        agreeing = ["Architect", "Builder", "Sentinel", "Provocateur"]
        can_approve, msg = self.budget.check_approval(scope, agreeing, human_available=True)
        print(f"Budget check: {msg}")

        # Deliberate
        result = await self.deliberation.deliberate(task)

        # Print results
        print("\n--- DELIBERATION RESULT ---")
        print(f"Decision: {result.decision.chosen_path}")
        print(f"Confidence: {result.decision.confidence:.0%}")
        print(f"Requires human: {result.decision.requires_human}")

        if result.decision.dissent_recorded:
            print(f"\nDissent recorded: {len(result.decision.dissent_recorded)} voices")
            for d in result.decision.dissent_recorded:
                print(f"  - {d.voice.name}: {d.position}")

        if result.overseer_intervention:
            print(f"\n{result.overseer_intervention}")

        # Record in memory
        self.memory.add(
            content=task,
            context=result.decision.chosen_path,
            outcome="success" if result.decision.confidence > 0.5 else "pending",
            emotional_intensity=result.decision.confidence,
            tags=["deliberation", scope.value]
        )

        # Record budget
        self.budget.record_decision(
            scope, task,
            [d.voice.name for d in result.contributions],
            not result.decision.requires_human
        )

        return {
            "task": task,
            "scope": scope.value,
            "decision": result.decision.chosen_path,
            "confidence": result.decision.confidence,
            "requires_human": result.decision.requires_human,
            "dissent": [d.voice.name for d in result.decision.dissent_recorded],
            "votes": result.decision.votes
        }

    async def learn_from_failure(self, failure: str):
        """Run failure archaeology on a failed task."""
        print(f"\n{'='*60}")
        print(f"NEXUS Excavating Failure: {failure}")
        print(f"{'='*60}")

        result = await self.archaeologist.excavate(failure)

        print("\n--- EXCAVATION RESULT ---")
        print(result.summary())

        return result

    def status(self) -> str:
        """Get NEXUS status."""
        lines = [
            "=" * 40,
            "NEXUS STATUS",
            "=" * 40,
            f"\nCore: {len(self.core.list_voices())} voices",
            f"Memory: {self.memory.summary()}",
            f"\n{self.budget.get_status()}",
        ]
        return "\n".join(lines)

    def memory_insights(self) -> list[str]:
        """Get memory insights."""
        return self.memory.get_insights()


async def main():
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="NEXUS - Multi-Voice Deliberative Agent")
    parser.add_argument("command", nargs="?", default="status", help="Command to run")
    parser.add_argument("task", nargs="?", help="Task description")
    parser.add_argument("--model", default="qwen2.5:7b", help="Ollama model")
    parser.add_argument("--fail", action="store_true", help="Report a failure for archaeology")

    args = parser.parse_args()

    nexus = Nexus(model=args.model)

    if args.command == "status":
        print(nexus.status())

    elif args.command == "think" and args.task:
        result = await nexus.think(args.task)
        print(f"\n✓ Decision: {result['decision']}")

    elif args.command == "learn" and args.task:
        await nexus.learn_from_failure(args.task)

    elif args.command == "memory":
        insights = nexus.memory_insights()
        print("Memory Insights:")
        for i in insights:
            print(f"  • {i}")

    else:
        print("Commands:")
        print("  nexus status          - Show NEXUS status")
        print("  nexus think \"task\"    - Deliberate on a task")
        print("  nexus learn \"failure\" - Run failure archaeology")
        print("  nexus memory          - Show memory insights")


if __name__ == "__main__":
    asyncio.run(main())
