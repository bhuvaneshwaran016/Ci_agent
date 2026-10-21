
import requests
from pathlib import Path

# Find the project directory
BASE_DIR = Path(__file__).parent

# Location of the Docker test log
LOG_FILE = BASE_DIR / "investigation_logs" / "test_results.log"

# Name of our local AI model
MODEL = "qwen2.5:3b"

# Read the error log
if not LOG_FILE.exists():
    print("Error log not found. Run main.py first.")
    raise SystemExit(1)

error_log = LOG_FILE.read_text(encoding="utf-8")

# Tell the AI what we want it to investigate
prompt = f"""
You are a software debugging assistant.

Analyze the following Python test failure.

Explain:
1. What failed?
2. What is the likely root cause?
3. What change would fix the problem?
4. What test should be run to verify the fix?

Do not claim that you changed or tested any code.

Test log:
{error_log}
"""

print("Asking the local AI to investigate...")

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
    explanation = response.json()["response"]

    # Save the AI's investigation report
    report_file = (
        BASE_DIR / "investigation_logs" / "ai_investigation.txt"
    )
    report_file.write_text(explanation, encoding="utf-8")

    print("\nAI Investigation Report:")
    print(explanation)
    print(f"\nReport saved to: {report_file}")

except requests.RequestException as error:
    print("Could not connect to Ollama.")
    print("Check that Ollama is running.")
    print(f"Details: {error}")
