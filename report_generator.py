
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).parent
LOG_DIR = BASE_DIR / "investigation_logs"
REPORT_FILE = LOG_DIR / "investigation_report.md"


def generate_report():
    LOG_DIR.mkdir(exist_ok=True)

    original_log = LOG_DIR / "original_test_results.log"

    attempt_logs = sorted(
        LOG_DIR.glob("attempt_*_test_results.log"),
        key=lambda path: int(
            path.name.split("_")[1]
        ),
    )

    lines = [
        "# AI Bug-Fixing Investigation Report",
        "",
        f"Generated: {datetime.now():%Y-%m-%d %H:%M:%S}",
        "",
        "## Original Test Results",
        "",
    ]

    if original_log.exists():
        lines.append(original_log.read_text(
            encoding="utf-8",
            errors="replace"
        ))
    else:
        lines.append("Original test log not found.")

    lines.extend(["", "## Repair Attempts", ""])

    if not attempt_logs:
        lines.append("No repair attempt logs found.")

    for log in attempt_logs:
        content = log.read_text(
            encoding="utf-8",
            errors="replace"
        )

        lines.extend([
            f"### {log.name}",
            "",
            "```text",
            content,
            "```",
            "",
        ])

    candidate = BASE_DIR / "workspace" / "app.py"

    lines.extend([
        "## Final Candidate",
        "",
        f"Candidate file: `{candidate}`",
        "",
    ])

    if candidate.exists():
        lines.append("Candidate source code:")
        lines.extend([
            "",
            "```python",
            candidate.read_text(
                encoding="utf-8",
                errors="replace"
            ),
            "```",
        ])
    else:
        lines.append("Candidate source file not found.")

    REPORT_FILE.write_text(
        "\n".join(lines),
        encoding="utf-8",
    )

    print("Investigation report generated!")
    print(f"Report location: {REPORT_FILE}")


if __name__ == "__main__":
    generate_report()
