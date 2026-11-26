"""Text and JSON report rendering for :class:`DiffResult`."""

from __future__ import annotations

import json

from .differ import SEVERITY_BREAKING, SEVERITY_INFO, SEVERITY_NON_BREAKING, DiffResult

_LABELS = {
    SEVERITY_BREAKING: "BREAKING",
    SEVERITY_NON_BREAKING: "NON-BREAKING",
    SEVERITY_INFO: "INFO",
}


def render_text(result: DiffResult) -> str:
    """Render a human-readable report."""
    summary = result.summary
    lines = [
        "OpenAPI diff report",
        "===================",
        (
            f"Summary: {summary['total']} change(s) - "
            f"{summary['breaking']} breaking, "
            f"{summary['non_breaking']} non-breaking, "
            f"{summary['info']} info"
        ),
        "",
    ]
    if not result.changes:
        lines.append("No changes detected.")
        return "\n".join(lines) + "\n"

    for severity in (SEVERITY_BREAKING, SEVERITY_NON_BREAKING, SEVERITY_INFO):
        group = [c for c in result.changes if c.severity == severity]
        if not group:
            continue
        lines.append(f"{_LABELS[severity]} ({len(group)}):")
        for change in group:
            lines.append(
                f"  [{_LABELS[severity]}] {change.kind} at {change.location}: "
                f"{change.message}"
            )
            lines.append(f"      Reason: {change.reason}")
        lines.append("")

    lines.append(
        "Result: BREAKING CHANGES FOUND" if result.has_breaking else "Result: no breaking changes"
    )
    return "\n".join(lines) + "\n"


def render_json(result: DiffResult) -> str:
    """Render a machine-readable JSON report."""
    return json.dumps(result.to_dict(), indent=2) + "\n"
