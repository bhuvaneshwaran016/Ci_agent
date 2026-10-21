
import subprocess
from pathlib import Path

from workspace_manager import create_workspace
from fix_generator import generate_fix

BASE_DIR = Path(__file__).parent
LOG_DIR = BASE_DIR / "investigation_logs"
LOG_DIR.mkdir(exist_ok=True)

ORIGINAL_DIR = BASE_DIR / "sample_project"
WORKSPACE_DIR = BASE_DIR / "workspace"


def run_docker_tests(project_dir, image_name, log_name):
    log_file = LOG_DIR / log_name

    print(f"\nBuilding Docker image: {image_name}")

    try:
        
        build = subprocess.run(
            ["docker", "build", "-t", image_name, str(project_dir)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
        )

    except subprocess.TimeoutExpired:
        message = "Docker build timed out."
        log_file.write_text(message, encoding="utf-8")
        print(message)
        return "infrastructure_error", message
    except FileNotFoundError:
        message = "Docker was not found. Check Docker Desktop."
        log_file.write_text(message, encoding="utf-8")
        print(message)
        return "infrastructure_error", message

    build_output = (build.stdout or "") + (build.stderr or "")

    if build.returncode != 0:
        log_file.write_text(build_output, encoding="utf-8")
        print(build_output)
        return "infrastructure_error", build_output

    print("\nRunning tests inside Docker...")

    try:
        result = subprocess.run(
            ["docker", "run", "--rm", image_name],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        message = "Docker tests timed out."
        log_file.write_text(message, encoding="utf-8")
        print(message)
        return "infrastructure_error", message

    output = result.stdout + result.stderr
    log_file.write_text(output, encoding="utf-8")
    print(output)

    if result.returncode == 0:
        return "passed", output

    if "FAILED" in output or "ERROR" in output:
        return "test_failed", output

    return "infrastructure_error", output


def main():
    print("STEP 1: Testing original project")

    status, _ = run_docker_tests(
        ORIGINAL_DIR,
        "ci-agent-original",
        "original_test_results.log",
    )

    if status == "passed":
        print("Original tests already pass. No fix is needed.")
        return

    if status == "infrastructure_error":
        print("Could not test the original project reliably.")
        print("Fix the Docker or test-environment problem first.")
        return

    print("\nSTEP 2: Creating isolated workspace")

    try:
        create_workspace()
    except (FileNotFoundError, OSError) as error:
        print(f"Workspace creation failed: {error}")
        return

    latest_log = LOG_DIR / "original_test_results.log"
    attempt = 1

    print("\nStarting unlimited fix-and-test loop.")
    print("The agent stops when tests pass or an operational error occurs.")
    print("Press Ctrl+C to stop manually.")

    while True:
        print(f"\n{'=' * 45}")
        print(f"FIX ATTEMPT {attempt}")
        print(f"{'=' * 45}")

        # Generate a fix using the current workspace code
        # and the latest test failure.
        try:
            fix_generated = generate_fix(latest_log, attempt)
        except Exception as error:
            print(f"AI fix generation failed: {error}")
            print("Stopping so you can investigate the problem.")
            return

        
        if fix_generated == "invalid_code":
            latest_log = (
                LOG_DIR
                / f"ai_syntax_error_attempt_{attempt}.log"
            )

            attempt += 1
            continue

        if not fix_generated:
            print("AI could not generate a fix. Stopping.")
            return


        log_name = f"attempt_{attempt}_test_results.log"
        image_name = f"ci-agent-fixed-attempt-{attempt}"

        status, output = run_docker_tests(
            WORKSPACE_DIR,
            image_name,
            log_name,
        )

        if status == "passed":
            print(f"\nSUCCESS! Tests passed on attempt {attempt}.")
            print(f"Verified candidate: {WORKSPACE_DIR / 'app.py'}")
            print("The original project remains unchanged.")
            print("Review the candidate before using it in production.")
            return

        if status == "infrastructure_error":
            print("Docker infrastructure error detected.")
            print("Fix the environment before continuing.")
            return

        # Keep retrying, even if the same error occurs again.
        latest_log = LOG_DIR / log_name
        attempt += 1

        print("Tests failed. Sending the latest failure to the AI.")
        print("The next attempt will use the current candidate code.")

        
if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nAgent stopped manually.")
        print("The original project remains unchanged.")
        print(f"Review candidate code: {WORKSPACE_DIR / 'app.py'}")
