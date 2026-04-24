"""Agents package - Modular agent framework for Karma.

Agents are functional roles, NOT personalities. They are tools that Karma
can invoke, load, unload, and ignore. Karma remains in control.
"""

from agents.base_agent import (
    BaseAgent,
    AgentStatus,
    AgentCapabilities,
    AgentContext,
    AgentResult,
    NullAgent,
)

from agents.planner_agent import PlannerAgent, create_planner_agent
from agents.executor_agent import ExecutorAgent, create_executor_agent
from agents.retriever_agent import RetrieverAgent, create_retriever_agent
from agents.summarizer_agent import SummarizerAgent, create_summarizer_agent
from agents.critic_agent import CriticAgent, create_critic_agent
from agents.navigator_agent import NavigatorAgent, create_navigator_agent


def get_all_agents():
    """Get all available agent instances."""
    return {
        "planner": create_planner_agent(),
        "executor": create_executor_agent(),
        "retriever": create_retriever_agent(),
        "summarizer": create_summarizer_agent(),
        "critic": create_critic_agent(),
        "navigator": create_navigator_agent(),
    }


def get_agent_by_role(role: str):
    """Get agent instance by role name."""
    agents = get_all_agents()
    return agents.get(role)


__all__ = [
    "BaseAgent",
    "AgentStatus",
    "AgentCapabilities",
    "AgentContext",
    "AgentResult",
    "NullAgent",
    "PlannerAgent",
    "ExecutorAgent",
    "RetrieverAgent",
    "SummarizerAgent",
    "CriticAgent",
    "NavigatorAgent",
    "create_planner_agent",
    "create_executor_agent",
    "create_retriever_agent",
    "create_summarizer_agent",
    "create_critic_agent",
    "create_navigator_agent",
    "get_all_agents",
    "get_agent_by_role",
]
