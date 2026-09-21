"""Enterprise benchmark JSON and Markdown reporting."""

from __future__ import annotations

import json
from pathlib import Path


def write_report(report: dict, output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "latest.json"
    markdown_path = output_dir / "latest.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    lines = [
        "# Enterprise Data Agent Benchmark",
        "",
        f"- Status: **{report['status']}**",
        f"- Cases: **{report['totals']['cases']}**",
        f"- Passed: **{report['totals']['pass']}**",
        f"- Failed: **{report['totals']['fail']}**",
        "",
        "## Metrics",
        "",
        "```json",
        json.dumps(report["metrics"], ensure_ascii=False, indent=2),
        "```",
        "",
        "## Cases",
        "",
        "| ID | Category | Status | Detail |",
        "|---|---|---:|---|",
    ]
    for case in report["cases"]:
        lines.append(
            f"| {case['id']} | {case['category']} | {case['status']} | "
            f"{str(case.get('detail', '')).replace('|', '/')} |"
        )
    markdown_path.write_text("\n".join(lines) + "\n")
    return json_path, markdown_path


__all__ = ["write_report"]
