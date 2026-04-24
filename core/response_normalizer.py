"""Response Normalizer - Formats responses in Karma's voice.

Post-processes outputs to ensure consistent Karma formatting
and tone regardless of source (agent/model/tool).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class NormalizationRules:
    """Rules for response normalization."""
    prefix: Optional[str] = None
    suffix: Optional[str] = None
    format_markdown: bool = True
    max_length: int = 10000
    strip_excess_newlines: bool = True
    normalize_whitespace: bool = True


class ResponseNormalizer:
    """Normalizes responses to Karma's standard format.
    
    Ensures all responses follow Karma's formatting conventions,
    regardless of whether they came from agents, models, or tools.
    """

    def __init__(self, rules: Optional[NormalizationRules] = None):
        self.rules = rules or NormalizationRules()

    def normalize(self, content: Any, response_type: str = "general") -> str:
        """Normalize content to Karma's response format.
        
        Args:
            content: Raw content to normalize
            response_type: Type of response (general, error, success, etc.)
            
        Returns:
            Normalized string
        """
        # Convert to string
        output = str(content) if not isinstance(content, str) else content

        # Apply whitespace normalization
        if self.rules.normalize_whitespace:
            output = self._normalize_whitespace(output)

        # Strip excess newlines
        if self.rules.strip_excess_newlines:
            output = self._strip_excess_newlines(output)

        # Enforce length
        if len(output) > self.rules.max_length:
            output = output[:self.rules.max_length] + "... (truncated)"

        # Add prefix/suffix
        if self.rules.prefix:
            output = f"{self.rules.prefix}\n{output}"

        if self.rules.suffix:
            output = f"{output}\n{self.rules.suffix}"

        return output

    def _normalize_whitespace(self, text: str) -> str:
        """Normalize whitespace."""
        # Replace multiple spaces with single space
        import re
        text = re.sub(r' +', ' ', text)
        # Replace tabs with spaces
        text = text.replace('\t', ' ')
        return text

    def _strip_excess_newlines(self, text: str) -> str:
        """Strip excess newlines."""
        # Replace 3+ newlines with double newline
        import re
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text

    def format_error(self, error: str, context: Optional[str] = None) -> str:
        """Format error response."""
        lines = [
            "**Error**",
            "",
            error,
        ]

        if context:
            lines.extend(["", f"Context: {context}"])

        return self.normalize("\n".join(lines), "error")

    def format_success(self, message: str, details: Optional[Dict] = None) -> str:
        """Format success response."""
        lines = [
            message,
        ]

        if details:
            lines.append("")
            for key, value in details.items():
                lines.append(f"- **{key}**: {value}")

        return self.normalize("\n".join(lines), "success")

    def format_info(self, title: str, content: str) -> str:
        """Format informational response."""
        lines = [
            f"## {title}",
            "",
            content,
        ]

        return self.normalize("\n".join(lines), "info")

    def format_list(self, items: List[str], title: Optional[str] = None) -> str:
        """Format list response."""
        lines = []

        if title:
            lines.extend([f"## {title}", ""])

        for item in items:
            lines.append(f"- {item}")

        return self.normalize("\n".join(lines), "list")


_global_normalizer: Optional[ResponseNormalizer] = None


def get_response_normalizer() -> ResponseNormalizer:
    """Get global response normalizer."""
    global _global_normalizer
    if _global_normalizer is None:
        _global_normalizer = ResponseNormalizer()
    return _global_normalizer
