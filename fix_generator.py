
import ast
import requests
from pathlib import Path

BASE_DIR = Path(__file__).parent
BACKUP_DIR = BASE_DIR / "investigation_logs" / "backups"

MODEL = "qwen2.5:3b"


def generate_fix(source_file, error_log_path, attempt):
    source_file = Path(source_file)
    error_log_path = Path(error_log_path)

    if not source_file.exists():
        print(f"Workspace code not found: {source_file}")
        return False

    if not error_log_path.exists():
        print(f"Error log not found: {error_log_path}")
        return False

    # Read the latest code and latest failure.
    current_code = source_file.read_text(encoding="utf-8")
    error_log = error_log_path.read_text(encoding="utf-8")

    prompt = f"""
You are an expert Python debugging assistant.

Fix the current code using the latest test failure.

Rules:
- Return the complete corrected Python source code only.
- Do not use Markdown code fences.
- Keep existing function names.
- Do not modify the tests.
- Preserve the intended behavior.
- Consider the current code and latest failure together.
- Do not claim that you tested the code.

Current Python code:
{current_code}

Latest test failure:
{error_log}
"""

    print(
        f"Asking Ollama to fix {source_file.name}, "
        f"attempt {attempt}..."
    )

    try:
        response = requests.post(
            "http://localhost:11434/api/generate",
            json={
                "model": MODEL,
                "prompt": prompt,
                "stream": False,
            },
            timeout=180,
        )

        response.raise_for_status()
        fixed_code = response.json()["response"].strip()

    except (requests.RequestException, KeyError, ValueError) as error:
        print(f"Could not obtain a valid AI response: {error}")
        return False

    # Remove Markdown code fences if present.
    if fixed_code.startswith("```"):
        lines = fixed_code.splitlines()

        if lines and lines[0].startswith("```"):
            lines = lines[1:]

        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]

        fixed_code = "\n".join(lines).strip()

    if not fixed_code:
        print("AI returned empty code. Fix rejected.")
        return False

    # Validate Python syntax before changing the workspace.
    try:
        ast.parse(fixed_code)

    except SyntaxError as error:
        print("AI generated invalid Python syntax.")
        print(f"Details: {error}")

        syntax_error_log = (
            BASE_DIR
            / "investigation_logs"
            / f"ai_syntax_error_attempt_{attempt}.log"
        )

        syntax_error_log.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        syntax_error_log.write_text(
            f"""
The AI generated invalid Python syntax.

Error details:
Line: {error.lineno}
Column: {error.offset}
Message: {error.msg}
Problematic line: {error.text}

Current code:
{current_code}

The generated code was rejected.
Please generate valid Python code.
""",
            encoding="utf-8",
        )

        print(f"Syntax error saved: {syntax_error_log}")
        print("Existing workspace code is preserved.")

        return "invalid_code"

    # Back up the current version before applying the new proposal.
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    backup_file = (
        BACKUP_DIR
        / f"{source_file.stem}.before_attempt_{attempt}.py"
    )

    backup_file.write_text(current_code, encoding="utf-8")

    source_file.write_text(
        fixed_code + "\n",
        encoding="utf-8",
    )

    print("Syntax validation passed.")
    print(f"Backup saved: {backup_file}")
    print(f"New proposal saved to: {source_file}")

    return True


if __name__ == "__main__":
    print("Run main.py to execute the complete fix-and-test workflow.")
