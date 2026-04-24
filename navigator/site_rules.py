"""Site Rules - Rules for different site navigation."""

from __future__ import annotations

import re
from typing import Dict, List
from dataclasses import dataclass


@dataclass
class SiteRule:
    """Rules for a specific site."""
    site_name: str
    base_url: str
    link_pattern: str  # Pattern for internal links
    ignore_patterns: List[str]  # Patterns to ignore
    max_depth: int
    max_pages: int
    prefer_sections: List[str]  # Preferred section patterns
    extract_summary: bool


# Wikipedia rules
WIKIPEDIA_RULES = SiteRule(
    site_name="wikipedia",
    base_url="https://en.wikipedia.org",
    link_pattern=r"/wiki/[^:]+",  # Article links only
    ignore_patterns=[
        r"/wiki/Help:",
        r"/wiki/Wikipedia:",
        r"/wiki/Template:",
        r"/wiki/Category:",
        r"/wiki/Portal:",
        r"/wiki/Book:",
        r"/wiki/Talk:",
        r"/wiki/Special:",
        r"/wiki/Main_Page",
        r"/wiki/Index:",
        r"/wiki/File:",
        r"/wiki/Module:",
        r"az\.wikipedia\.org",
        r"ru\.wikipedia\.org",
        r"de\.wikipedia\.org",
        r"fr\.wikipedia\.org",
        r"es\.wikipedia\.org",
        r"it\.wikipedia\.org",
        r"pt\.wikipedia\.org",
        r"zh\.wikipedia\.org",
        r"ja\.wikipedia\.org",
        r"ar\.wikipedia\.org",
        r"wikipedia\.org/wiki/[^/]*:$",
    ],
    max_depth=2,
    max_pages=6,
    prefer_sections=[
        r"==\s*Introduction\s*==",
        r"==\s*Overview\s*==",
        r"==\s*History\s*==",
        r"==\s*Architecture\s*==",
        r"==\s*Features\s*==",
        r"==\s*Usage\s*==",
        r"==\s*Installation\s*==",
        r"==\s*Tools\s*==",
    ],
    extract_summary=True,
)


# Generic documentation site rules
DOCS_RULES = SiteRule(
    site_name="docs",
    base_url="",
    link_pattern=r"/docs?/[^/]+",
    ignore_patterns=[
        r"/api/",
        r"/reference/",
        r"/archive/",
    ],
    max_depth=2,
    max_pages=5,
    prefer_sections=[
        r"^#\s+",
        r"^##\s+",
    ],
    extract_summary=True,
)


class SiteRuleEngine:
    """Engine for applying site-specific rules."""

    def __init__(self):
        self.rules: Dict[str, SiteRule] = {
            "wikipedia": WIKIPEDIA_RULES,
            "docs": DOCS_RULES,
        }
        self.default_rule = SiteRule(
            site_name="default",
            base_url="",
            link_pattern=r".*",
            ignore_patterns=[],
            max_depth=1,
            max_pages=3,
            prefer_sections=[],
            extract_summary=False,
        )

    def get_rule(self, site_name: str) -> SiteRule:
        """Get rules for a specific site."""
        return self.rules.get(site_name, self.default_rule)

    def is_valid_link(self, url: str, rule: SiteRule) -> bool:
        """Check if a link is valid according to rules."""
        # Check ignore patterns
        for pattern in rule.ignore_patterns:
            if re.search(pattern, url, re.IGNORECASE):
                return False

        # Check link pattern
        if rule.link_pattern and not re.search(rule.link_pattern, url):
            return False

        return True

    def filter_links(self, links: List[str], rule: SiteRule) -> List[str]:
        """Filter links according to site rules."""
        filtered = []
        for link in links:
            if self.is_valid_link(link, rule):
                filtered.append(link)
        return filtered

    def extract_summary(self, content: str, rule: SiteRule) -> str:
        """Extract summary from content based on site rules."""
        if not rule.extract_summary:
            return content[:1000]

        # For Wikipedia, try to extract lead paragraph
        if rule.site_name == "wikipedia":
            # Find the lead paragraph (first paragraph before first h2)
            match = re.search(r"^(.+?)\n==", content, re.MULTILINE | re.DOTALL)
            if match:
                return match.group(1).strip()[:1000]

        # Default: return first 1000 chars
        return content[:1000]

    def score_link(self, url: str, topic: str, rule: SiteRule) -> float:
        """Score a link based on topic relevance."""
        url_lower = url.lower()
        topic_lower = topic.lower()

        # Check if URL contains topic keywords
        score = 0.0

        # Direct topic match in URL
        for word in topic_lower.split():
            if word in url_lower:
                score += 0.5

        # Prefer main article over subpages
        if url.count("/") == url_base_path(url).count("/") + 1:
            score += 0.2

        # Wikipedia-specific scoring
        if rule.site_name == "wikipedia":
            # Prefer non-parenthesized titles
            if "(" not in url:
                score += 0.1

            # Penalize disambiguation pages
            if "disambiguation" in url_lower:
                score -= 0.3

        return score


def url_base_path(url: str) -> str:
    """Get the base path of a URL."""
    parts = url.split("/")
    if len(parts) >= 3:
        return "/".join(parts[:3])
    return url


def create_rule_for_url(url: str) -> SiteRule:
    """Create appropriate rule based on URL."""
    if "wikipedia.org" in url:
        return WIKIPEDIA_RULES
    elif "/docs/" in url:
        return DOCS_RULES
    else:
        return SiteRule(
            site_name="generic",
            base_url="",
            link_pattern=r".*",
            ignore_patterns=[],
            max_depth=1,
            max_pages=3,
            prefer_sections=[],
            extract_summary=False,
        )
