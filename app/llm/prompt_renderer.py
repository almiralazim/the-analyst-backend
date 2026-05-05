"""Prompt template renderer with Jinja2-style variable substitution."""

from __future__ import annotations

import re
from pathlib import Path


def render_prompt(template_path: str | Path, context: dict) -> str:
    """Load a markdown prompt template and substitute {{VARIABLES}}.

    Args:
        template_path: Path to the .md prompt template file.
        context: Dictionary of variable names to values.

    Returns:
        Rendered prompt string with all variables substituted.
    """
    template_path = Path(template_path)
    if not template_path.exists():
        raise FileNotFoundError(f"Prompt template not found: {template_path}")

    template = template_path.read_text(encoding="utf-8")
    return render_template_string(template, context)


def render_template_string(template: str, context: dict) -> str:
    """Substitute {{VARIABLE}} placeholders in a template string.

    Unresolved variables are left as-is (not removed) so agents
    can see what context was missing.
    """
    def replacer(match: re.Match) -> str:
        key = match.group(1).strip()
        value = context.get(key)
        if value is None:
            return match.group(0)  # Leave unresolved
        if isinstance(value, list):
            return "\n".join(str(item) for item in value)
        return str(value)

    return re.sub(r"\{\{(\s*[A-Z_][A-Z0-9_]*\s*)\}\}", replacer, template)
