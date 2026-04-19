"""Context7 Routing - Route queries to appropriate knowledge sources.

Context7 is a documentation search provider. Queries involving:
- library
- framework  
- API
- SDK

Should route to Context7 provider. Otherwise use:
- navigator (Wikipedia)
- local knowledge (spine)
- golearn
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple


CONTEXT7_TRIGGERS = [
    "library", "framework", "api", "sdk",
    "module", "package", "import", "reference",
    "documentation", "docs", "manual",
    "tutorial", "guide", "how to",
    "example", "usage", "installation",
    "config", "configuration", "setup",
]


LIBRARY_PATTERNS = [
    r"python.*(library|module|package)",
    r"(library|module|package).*python",
    r"(install|use).*(pip|conda)",
    r"(import|from)\s+\w+",
    r"(api|rest|http).*(request|response)",
    r"(function|class|method).*(parameter|arg)",
]


def should_route_to_context7(query: str) -> bool:
    """Determine if query should route to Context7 provider."""
    query_lower = query.lower()
    
    for trigger in CONTEXT7_TRIGGERS:
        if trigger in query_lower:
            return True
    
    for pattern in LIBRARY_PATTERNS:
        import re
        if re.search(pattern, query_lower):
            return True
    
    return False


def route_query(query: str) -> Dict[str, Any]:
    """Route a query to appropriate knowledge source(s).
    
    Returns routing decision with reasoning.
    """
    query_lower = query.lower()
    
    routes = []
    
    if should_route_to_context7(query):
        routes.append({
            "source": "context7",
            "priority": 1,
            "reason": "query involves library/API/framework",
        })
    
    routes.append({
        "source": "spine",
        "priority": 2,
        "reason": "local knowledge search",
    })
    
    if any(word in query_lower for word in ["what", "who", "when", "where"]):
        routes.append({
            "source": "navigator",
            "priority": 3,
            "reason": "factual query - Wikipedia",
        })
    
    routes.append({
        "source": "golearn",
        "priority": 4,
        "reason": "research needed",
    })
    
    routes.sort(key=lambda x: x["priority"])
    
    return {
        "query": query,
        "routes": routes,
        "primary": routes[0]["source"] if routes else "spine",
    }


def get_context7_query(topic: str) -> str:
    """Transform topic into Context7 search query."""
    topic_lower = topic.lower()
    
    if "python" in topic_lower:
        if "library" not in topic_lower and "module" not in topic_lower:
            return f"python {topic} documentation"
    
    if "javascript" in topic_lower or "js" in topic_lower:
        if "library" not in topic_lower and "framework" not in topic_lower:
            return f"javascript {topic} mdn"
    
    return f"{topic} documentation"


class QueryRouter:
    """Route queries to appropriate knowledge sources."""
    
    def __init__(self):
        self.route_history: List[Dict[str, Any]] = []
    
    def route(self, query: str) -> Dict[str, Any]:
        """Route a query."""
        decision = route_query(query)
        self.route_history.append(decision)
        return decision
    
    def get_stats(self) -> Dict[str, int]:
        """Get routing statistics."""
        stats: Dict[str, int] = {}
        for decision in self.route_history:
            source = decision.get("primary", "unknown")
            stats[source] = stats.get(source, 0) + 1
        return stats
