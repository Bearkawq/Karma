"""GoLearn Integration with Knowledge Spine.

This module integrates GoLearn results into the unified Knowledge Spine.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def integrate_golearn_to_spine(golearn_result: Dict[str, Any]) -> int:
    """Integrate GoLearn results into the Knowledge Spine.
    
    Returns the number of chunks ingested.
    """
    try:
        from research.knowledge_spine import get_spine
        
        spine = get_spine()
        
        topic = golearn_result.get("topic", "general")
        session_id = golearn_result.get("session_id", "unknown")
        
        chunks_ingested = 0
        
        output = golearn_result.get("output", "")
        if output and len(output) > 50:
            spine.ingest(
                content=output[:30000],
                source_type="navigator",
                provenance=f"golearn:{session_id}",
                topic=topic,
                title=f"GoLearn: {topic}",
                tags=["golearn", "research"],
                trust_score=0.75,
            )
            chunks_ingested += 1
        
        sources = golearn_result.get("sources", [])
        for source in sources[:10]:
            if isinstance(source, dict):
                content = source.get("content", "") or source.get("text", "")
                url = source.get("url", "")
                title = source.get("title", "Unknown")
                
                if content and len(content) > 100:
                    spine.ingest(
                        content=content[:20000],
                        source_type="navigator",
                        provenance=f"golearn_source:{session_id}",
                        topic=topic,
                        source_url=url,
                        title=title,
                        tags=["golearn", "source"],
                        trust_score=0.7,
                    )
                    chunks_ingested += 1
        
        return chunks_ingested
        
    except Exception as e:
        return 0


def get_golearn_context(topic: str, limit: int = 5) -> List[str]:
    """Get GoLearn context from the Knowledge Spine for a topic.
    
    Returns list of content snippets.
    """
    try:
        from research.knowledge_spine import get_spine
        
        spine = get_spine()
        results = spine.retrieve(topic=topic, limit=limit, min_trust=0.6)
        
        return [r.chunk.content[:500] for r in results]
        
    except Exception:
        return []
