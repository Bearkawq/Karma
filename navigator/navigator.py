"""Site Navigator - Main navigation coordinator.

Coordinates browsing, site rules, and crawl policy for intentional site navigation.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional
from dataclasses import dataclass

from .browser_agent import BrowserAgent
from .site_rules import SiteRuleEngine, create_rule_for_url


@dataclass
class NavigatedPage:
    """A page that was navigated to and extracted."""
    url: str
    title: str
    content: str
    depth: int
    provenance: str  # e.g., "wikipedia_navigation"
    topic: str
    links_followed: int = 0


@dataclass
class NavigationResult:
    """Result of a navigation session."""
    success: bool
    pages: List[NavigatedPage]
    stop_reason: str
    visited_count: int
    total_content: str


class SiteNavigator:
    """Main site navigation coordinator."""

    def __init__(self, session_dir: Optional[Path] = None):
        self.browser = BrowserAgent()
        self.rule_engine = SiteRuleEngine()
        self.session_dir = session_dir

        if session_dir:
            self.browser.set_session_dir(session_dir / "nav")

    def navigate(self, topic: str, site: str = "wikipedia",
                 max_pages: int = 5, max_depth: int = 2) -> NavigationResult:
        """Navigate a site to gather information on a topic."""

        # Determine starting URL
        start_url = self._get_start_url(site, topic)
        if not start_url:
            return NavigationResult(
                success=False,
                pages=[],
                stop_reason="invalid_site",
                visited_count=0,
                total_content="",
            )

        # Get site rules
        rule = create_rule_for_url(start_url)
        actual_max_pages = min(max_pages, rule.max_pages)
        actual_max_depth = min(max_depth, rule.max_depth)

        # Track pages and links
        pages: List[NavigatedPage] = []
        current_depth = 0
        queue: List[tuple] = [(start_url, 0)]  # (url, depth)

        # Emit pulse event if available
        self._emit_pulse("start", f"Opening {site} page for {topic}")

        while queue and len(pages) < actual_max_pages:
            url, depth = queue.pop(0)

            # Skip if already visited
            if self.browser.is_visited(url):
                self._emit_pulse("skip", f"Already visited: {url}")
                continue

            # Skip if beyond max depth
            if depth > actual_max_depth:
                continue

            # Fetch page
            self._emit_pulse("fetch", f"Fetching: {url}")
            result = self.browser.fetch(url, depth)

            if not result.success:
                self._emit_pulse("error", f"Failed: {result.error}")
                continue

            # Extract content
            summary = self.rule_engine.extract_summary(result.content, rule)

            # Create page record
            page = NavigatedPage(
                url=result.url,
                title=result.title,
                content=summary,
                depth=depth,
                provenance=f"{site}_navigation",
                topic=topic,
                links_followed=len(pages),
            )
            pages.append(page)

            self._emit_pulse("success", f"Extracted: {result.title[:40]}")

            # Get valid internal links for following
            if depth < actual_max_depth:
                valid_links = self.rule_engine.filter_links(
                    result.internal_links, rule
                )

                # Score and sort links
                scored_links = []
                for link in valid_links:
                    score = self.rule_engine.score_link(link, topic, rule)
                    scored_links.append((link, score))

                # Sort by score and add to queue
                scored_links.sort(key=lambda x: x[1], reverse=True)
                for link, score in scored_links[:3]:  # Top 3 links
                    if not self.browser.is_visited(link):
                        queue.append((link, depth + 1))

        # Determine stop reason
        if len(pages) >= actual_max_pages:
            stop_reason = "max_pages"
        elif not queue:
            stop_reason = "completed"
        else:
            stop_reason = "queue_empty"

        self._emit_pulse("stop", f"Navigation stopped: {stop_reason}")

        # Combine all content
        total_content = "\n\n---\n\n".join([
            f"# {p.title}\n\n{p.content}" for p in pages
        ])

        # Save to local knowledge
        self._save_to_knowledge(pages, topic, site)

        return NavigationResult(
            success=len(pages) > 0,
            pages=pages,
            stop_reason=stop_reason,
            visited_count=len(self.browser.visited),
            total_content=total_content,
        )

    def _get_start_url(self, site: str, topic: str) -> Optional[str]:
        """Get the starting URL for a site/topic."""
        topic_underscore = topic.replace(" ", "_")

        if site == "wikipedia":
            return f"https://en.wikipedia.org/wiki/{topic_underscore}"
        elif site == "docs":
            return f"https://docs.example.com/{topic_underscore}"

        return None

    def _emit_pulse(self, event_type: str, message: str):
        """Emit a pulse event if available."""
        try:
            from research.pulse import get_pulse
            pulse = get_pulse()
            pulse.emit_action(message, "navigator")
        except Exception:
            pass

    def _save_to_knowledge(self, pages: List[NavigatedPage], topic: str, site: str):
        """Save navigated pages to local knowledge."""
        try:
            from research.ingestor import get_ingestor

            ingestor = get_ingestor()

            for page in pages:
                from research.ingestor import IngestedItem, Provenance

                # Determine provenance
                prov = Provenance.CACHE if site == "wikipedia" else Provenance.WEB

                item = IngestedItem(
                    topic_bucket=topic.lower().replace(" ", "_"),
                    title=page.title[:100],
                    content=page.content[:50_000],
                    provenance=prov,
                    metadata={
                        "source_url": page.url,
                        "navigation_depth": page.depth,
                        "provenance": page.provenance,
                    },
                )

                ingestor.items.append(item)

        except Exception:
            pass  # Silently fail if knowledge save fails


def navigate_wikipedia(topic: str, max_pages: int = 5, max_depth: int = 2,
                       session_dir: Optional[Path] = None) -> NavigationResult:
    """Convenience function to navigate Wikipedia."""
    navigator = SiteNavigator(session_dir)
    return navigator.navigate(topic, "wikipedia", max_pages, max_depth)


def navigate_site(topic: str, site: str, max_pages: int = 5, max_depth: int = 2,
                   session_dir: Optional[Path] = None) -> NavigationResult:
    """Navigate a specific site."""
    navigator = SiteNavigator(session_dir)
    return navigator.navigate(topic, site, max_pages, max_depth)
