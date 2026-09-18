"""Machine- and human-readable evaluation reporting."""

from __future__ import annotations

import json
from pathlib import Path


def render_markdown(report: dict) -> str:
    metadata = report["metadata"]
    lines = [
        "# Agent Evaluation Report",
        "",
        f"- Timestamp: `{metadata['timestamp']}`",
        f"- Git SHA: `{metadata['git_sha']}`",
        f"- Environment: `{metadata['environment']}`",
        f"- Deterministic gate: **{report['deterministic_gate']}**",
        "",
        "| Suite | Status | Passed | Failed | Not run | Degraded |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for name in ("routing", "planning", "execution", "safety", "recovery", "rag"):
        section = report[name]
        totals = section.get("totals", {})
        lines.append(
            f"| {name} | {section['status']} | {totals.get('pass', 0)} | "
            f"{totals.get('fail', 0)} | {totals.get('not_run', 0)} | "
            f"{totals.get('degraded', 0)} |"
        )
    lines.extend(["", "## Metrics", ""])
    for name in ("routing", "planning", "execution", "safety", "recovery", "rag", "cost"):
        lines.extend(
            [
                f"### {name.title()}",
                "",
                "```json",
                json.dumps(report[name].get("metrics", report[name]), indent=2, ensure_ascii=False),
                "```",
                "",
            ]
        )
    return "\n".join(lines)


def write_report(report: dict, output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "latest.json"
    markdown_path = output_dir / "latest.md"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    markdown_path.write_text(render_markdown(report) + "\n")
    return json_path, markdown_path


__all__ = ["render_markdown", "write_report"]
