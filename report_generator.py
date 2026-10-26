
from pathlib import Path
from datetime import datetime
import re

BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "investigation_logs"
REPORT_FILE = LOG_DIR / "investigation_report.md"
WORKSPACE_DIR = BASE_DIR / "workspace"


def generate_report():
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    baseline_log = LOG_DIR / "baseline_test_results.log"
    workflow_logs = sorted(
        LOG_DIR.glob("workflow_*_logs.txt")
    ) + sorted(
        LOG_DIR.glob("selected_workflow_*.txt")
    )

    attempt_logs = sorted(
        LOG_DIR.glob("attempt_*_test_results.log"),
        key=lambda path: int(
            re.search(r"attempt_(\d+)", path.name).group(1)
        ),
    )

    lines = [
        "# AI Bug-Fixing Investigation Report",
        "",
        f"Generated: {datetime.now():%Y-%m-%d %H:%M:%S}",
        "",
        "## Summary",
        "",
    ]

    final_log = attempt_logs[-1] if attempt_logs else baseline_log

    if final_log.exists():
        final_text = final_log.read_text(
            encoding="utf-8",
            errors="replace",
        )
        if re.search(
            r"\b\d+\s+passed\b",
            final_text,
            re.IGNORECASE,
        ) and not re.search(
            r"\b\d+\s+failed\b",
            final_text,
            re.IGNORECASE,
        ):
            lines.append("Latest recorded test result: Tests passed.")
        else:
            lines.append(
                "Latest recorded test result: Review the final test log below."
            )
    else:
        lines.append("Final test result could not be determined.")

    lines.extend(["", "## Original Test Results", ""])

    if baseline_log.exists():
        lines.append(
            baseline_log.read_text(
                encoding="utf-8",
                errors="replace",
            )
        )
    else:
        lines.append("Baseline test log not found.")

    lines.extend(["", "## GitHub Workflow Logs", ""])

    if workflow_logs:
        for log in workflow_logs:
            lines.extend([
                f"### {log.name}",
                "",
                "```text",
                log.read_text(
                    encoding="utf-8",
                    errors="replace",
                ),
                "```",
                "",
            ])
    else:
        lines.append("No saved GitHub workflow logs found.")

    lines.extend(["", "## Repair Attempts", ""])

    if not attempt_logs:
        lines.append("No repair attempt logs found.")

    for log in attempt_logs:
        lines.extend([
            f"### {log.name}",
            "",
            "```text",
            log.read_text(
                encoding="utf-8",
                errors="replace",
            ),
            "```",
            "",
        ])

    lines.extend(["", "## Final Candidate Files", ""])

    if WORKSPACE_DIR.exists():
        candidates = [
            path for path in WORKSPACE_DIR.rglob("*.py")
            if not path.name.startswith("test_")
            and path.name != "conftest.py"
            and not any(
                part in {
                    ".git", ".venv", "__pycache__", ".pytest_cache"
                }
                for part in path.parts
            )
        ]

        if candidates:
            for candidate in candidates:
                relative_path = candidate.relative_to(BASE_DIR)

                lines.extend([
                    f"### `{relative_path}`",
                    "",
                    "```python",
                    candidate.read_text(
                        encoding="utf-8",
                        errors="replace",
                    ),
                    "```",
                    "",
                ])
        else:
            lines.append("No candidate Python source files found.")
    else:
        lines.append("Workspace not found.")

    REPORT_FILE.write_text(
        "\n".join(lines),
        encoding="utf-8",
    )

    print("Investigation report generated!")
    print(f"Report location: {REPORT_FILE}")


if __name__ == "__main__":
    generate_report()
