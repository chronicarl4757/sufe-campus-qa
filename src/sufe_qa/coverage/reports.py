"""覆盖报告文件输出辅助。"""

from __future__ import annotations

from pathlib import Path

from sufe_qa.coverage.audit import CoverageReport, render_markdown


def write_coverage_report(report: CoverageReport, json_path: Path, markdown_path: Path) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(report.to_json(), encoding="utf-8")
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
