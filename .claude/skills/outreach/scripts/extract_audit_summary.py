#!/usr/bin/env python3
"""Extract executive summary from Agentic Commerce Readiness Audit HTML.

Usage:
  python extract_audit_summary.py <path_to_audit.html>
  python extract_audit_summary.py dev/audits/loop_ars_report.html

Output: clean text of the executive summary paragraph.
"""

import html
import re
import sys


def extract_exec_summary(audit_path: str) -> str:
    try:
        with open(audit_path, "r", encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError:
        print(f"Error: Audit file not found at {audit_path}", file=sys.stderr)
        sys.exit(1)

    match = re.search(
        r'<div class="exec-summary-title">Executive Summary</div>\s*<p>(.*?)</p>',
        content,
        re.DOTALL,
    )

    if not match:
        print("Error: Executive summary not found in audit", file=sys.stderr)
        sys.exit(1)

    summary = match.group(1)
    summary = html.unescape(summary)
    summary = re.sub(r"</?(?:mark|strong)>", "", summary)
    summary = re.sub(r"\[\d+\]", "", summary)
    summary = re.sub(r"\s+", " ", summary).strip()

    return summary


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: extract_audit_summary.py <path_to_audit.html>")
        sys.exit(1)

    print(extract_exec_summary(sys.argv[1]))
