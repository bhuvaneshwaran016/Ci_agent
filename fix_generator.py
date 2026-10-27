import ast
import re
import requests
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
WORKSPACE_DIR = BASE_DIR / "workspace"
BACKUP_DIR = BASE_DIR / "investigation_logs" / "backups"
MODEL = "qwen2.5:3b"
OLLAMA_URL = "http://localhost:11434/api/generate"


def extract_python_code(raw_response: str) -> str:
    """Extract syntactically valid Python code from an LLM response safely."""
    if not raw_response:
        return ""

    # Remove UTF-8 BOM if present
    cleaned = raw_response.replace("\ufeff", "").strip()

    # Pattern for triple-backtick code fences (e.g., ```python ... ```)
    fence_pattern = re.compile(
        r"```(?:python|py)?\s*\n(.*?)\n```",
        re.DOTALL | re.IGNORECASE,
    )
    matches = fence_pattern.findall(cleaned)

    if matches:
        # If any block parses as valid Python AST, return the first valid one
        for block in matches:
            block_code = block.strip()
            try:
                ast.parse(block_code)
                return block_code
            except SyntaxError:
                continue
        # If none parse cleanly, return the longest block
        return max(matches, key=len).strip()

    # Handle unclosed code fence: ```python ...
    open_fence = re.search(
        r"```(?:python|py)?\s*\n(.*)",
        cleaned,
        re.DOTALL | re.IGNORECASE,
    )
    if open_fence:
        candidate = open_fence.group(1).rstrip("`").strip()
        try:
            ast.parse(candidate)
            return candidate
        except SyntaxError:
            pass

    # If no fences, filter out non-code commentary lines from the beginning/end
    lines = cleaned.splitlines()
    start_idx = 0
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        if (
            stripped.startswith((
                "#", "import ", "from ", "def ", "class ", "@", "try:", "with "
            ))
            or re.match(r"^[A-Za-z_]\w*\s*=", stripped)
            or re.match(r"^[A-Z_][A-Z0-9_]*\s*=", stripped)
        ):
            start_idx = idx
            break

    end_idx = len(lines)
    for idx in range(len(lines) - 1, start_idx - 1, -1):
        stripped = lines[idx].strip()
        if not stripped:
            continue
        if lines[idx].startswith(("    ", "\t")) or stripped.endswith((
            ":", ")", "]", "}", "pass", "return", "True", "False", "None"
        )):
            end_idx = idx + 1
            break
        if any(marker in stripped.lower() for marker in (
            "hope this", "explanation:", "let me know", "this code", "in this fix"
        )):
            end_idx = idx
            continue

    return "\n".join(lines[start_idx:end_idx]).strip()


def generate_fix(
    source_file,
    error_log_path,
    attempt,
    syntax_error_hint=None,
    regression_hint=None,
):
    source_file = Path(source_file)
    error_log_path = Path(error_log_path)

    if not source_file.is_file():
        print(f"Source file not found: {source_file}")
        return False, "Source file not found", ""

    if not error_log_path.is_file():
        print(f"Error log not found: {error_log_path}")
        return False, "Error log not found", ""

    current_code = source_file.read_text(
        encoding="utf-8-sig",
        errors="replace",
    )
    error_log = error_log_path.read_text(
        encoding="utf-8-sig",
        errors="replace",
    )

    failed_tests = re.findall(
        r"FAILED\s+([^\s]+)",
        error_log,
    )
    if not failed_tests:
        failed_tests = re.findall(
            r"([^\s:]+::test_\w+)\s+FAILED",
            error_log,
        )

    test_func_names = {
        t.split("::")[-1] for t in failed_tests if "::" in t
    }
    if not test_func_names:
        test_func_names = set(failed_tests)

    # Extract relevant failure traceback sections
    failure_sections = []
    for section in re.split(r"(?=_{3,}\s+\w+\s+_{3,})", error_log):
        if any(func in section for func in test_func_names):
            failure_sections.append(section.strip())

    if failure_sections:
        failure_details = "\n\n".join(failure_sections)[:8000]
    else:
        failure_details = error_log[-8000:]

    project_dir = source_file.parent
    for parent in source_file.parents:
        if parent.name == "workspace":
            break
        if (parent / "tests").is_dir():
            project_dir = parent
            break

    test_context = []
    for test_file in project_dir.rglob("test_*.py"):
        if any(
            part in {
                ".git", ".venv", "venv", "__pycache__",
                ".pytest_cache", "node_modules"
            }
            for part in test_file.parts
        ):
            continue

        try:
            content = test_file.read_text(
                encoding="utf-8-sig",
                errors="replace",
            )
            tree = ast.parse(content)
            for node in ast.walk(tree):
                if (
                    isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.name in test_func_names
                ):
                    segment = ast.get_source_segment(content, node)
                    if segment:
                        test_context.append(
                            f"# Test {node.name} from {test_file.name}:\n{segment}"
                        )
        except Exception:
            continue

    tests_text = "\n\n".join(test_context) if test_context else "No matching test function found."

    hint_lines = []
    if syntax_error_hint:
        hint_lines.append(
            f"IMPORTANT - PREVIOUS SYNTAX ERROR TO FIX: {syntax_error_hint}"
        )
    if regression_hint:
        hint_lines.append(
            f"IMPORTANT - PREVIOUS REGRESSIONS TO PREVENT: {regression_hint}"
        )
    hints_prompt = "\n".join(hint_lines)

    prompt = f"""You are an expert Python debugging agent. Your task is to fix the bug in the provided Python source file.

OBJECTIVE:
Repair `{source_file.name}` so that all failing tests pass without introducing any regressions in previously passing tests.

RULES:
1. Return ONLY the complete, corrected Python source file enclosed in ```python and ``` code fences.
2. Do NOT write any conversational text, explanations, or notes before or after the code fences.
3. Make minimal, targeted changes. Strictly preserve ALL existing functions, methods, classes, and signatures.
4. Do not hardcode test-specific return values; implement the correct business logic.
5. Ensure valid Python syntax with correct indentation.
{hints_prompt}

FAILING TESTS:
{failed_tests}

FAILURE TRACEBACKS:
{failure_details}

RELEVANT TEST CODE:
{tests_text}

SOURCE FILE TO REPAIR: {source_file.name}
```python
{current_code}
```
"""

    print(
        f"Asking Ollama to repair {source_file.name} (attempt {attempt})..."
    )

    try:
        response = requests.post(
            OLLAMA_URL,
            json={
                "model": MODEL,
                "prompt": prompt,
                "stream": False,
            },
            timeout=300,
        )
        response.raise_for_status()
        raw_response = response.json().get("response", "").strip()

    except (requests.RequestException, ValueError) as exc:
        print(f"Ollama request failed: {exc}")
        return False, f"Ollama request failed: {exc}", ""

    fixed_code = extract_python_code(raw_response)

    if not fixed_code:
        print("Ollama returned empty code.")
        return False, "Ollama returned empty code", ""

    # Validate syntax using AST parsing before accepting it as a candidate
    try:
        ast.parse(fixed_code)
    except SyntaxError as exc:
        syntax_log = (
            BASE_DIR / "investigation_logs"
            / f"ai_syntax_error_attempt_{attempt}.log"
        )
        syntax_log.parent.mkdir(parents=True, exist_ok=True)
        syntax_log.write_text(
            f"Generated code has a syntax error:\n{exc}\n\n"
            f"Line: {exc.lineno}, Offset: {exc.offset}\n"
            f"Source file: {source_file}\n"
            f"Problematic line: {exc.text or ''}\n\n"
            f"Raw LLM response:\n{raw_response}\n\n"
            f"Extracted code:\n{fixed_code}\n",
            encoding="utf-8",
        )
        error_summary = f"line {exc.lineno}: {exc.msg}"
        print(f"Attempt {attempt} rejected: Ollama generated invalid Python ({error_summary}).")
        print(f"Details saved to: {syntax_log}")
        return "invalid_code", error_summary, fixed_code

    # Candidate has valid syntax. Back up current code and write candidate.
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backup_file = (
        BACKUP_DIR
        / f"{source_file.stem}.before_attempt_{attempt}.py"
    )
    backup_file.write_text(current_code, encoding="utf-8")

    source_file.write_text(fixed_code + "\n", encoding="utf-8")
    print(f"Syntactically valid candidate written to: {source_file}")
    print(f"Previous version backed up to: {backup_file}")

    return True, None, fixed_code
