
import re
import subprocess
from pathlib import Path

from workspace_manager import create_workspace
from repository_manager import clone_repository
from test_download_logs import download_failed_workflow_logs
from fix_generator import generate_fix
from report_generator import generate_report


BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "investigation_logs"
WORKSPACE_DIR = BASE_DIR / "workspace"

LOG_DIR.mkdir(parents=True, exist_ok=True)


def save_investigation_report():
    """Generate the investigation report without hiding the main result."""
    try:
        generate_report()
    except Exception as error:
        print(f"Could not generate investigation report: {error}")


def run_docker_tests(project_dir, image_name, log_name):
    """Build a Docker image and run its tests."""
    log_file = LOG_DIR / log_name
    project_dir = Path(project_dir)

    if not (project_dir / "Dockerfile").is_file():
        message = f"Dockerfile not found in {project_dir}"
        log_file.write_text(message, encoding="utf-8")
        print(message)
        return "infrastructure_error", message

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
    except OSError as error:
        message = f"Docker build could not start: {error}"
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
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        message = "Docker tests timed out."
        log_file.write_text(message, encoding="utf-8")
        print(message)
        return "infrastructure_error", message
    except FileNotFoundError:
        message = "Docker was not found. Check Docker Desktop."
        log_file.write_text(message, encoding="utf-8")
        print(message)
        return "infrastructure_error", message
    except OSError as error:
        message = f"Docker tests could not start: {error}"
        log_file.write_text(message, encoding="utf-8")
        print(message)
        return "infrastructure_error", message

    output = (result.stdout or "") + (result.stderr or "")
    log_file.write_text(output, encoding="utf-8")
    print(output)

    if result.returncode == 0:
        return "passed", output

    if re.search(
        r"\bFAILED\b|\bERROR\b|AssertionError|"
        r"failed\s+tests?|\b\d+\s+failed\b",
        output,
        re.IGNORECASE,
    ):
        return "test_failed", output

    return "infrastructure_error", output


def find_test_project(workspace_dir):
    """Find a project directory containing a Dockerfile."""
    workspace_dir = Path(workspace_dir)

    preferred = workspace_dir / "sample_project"

    if (preferred / "Dockerfile").is_file():
        return preferred

    if (workspace_dir / "Dockerfile").is_file():
        return workspace_dir

    excluded_dirs = {
        ".git",
        ".venv",
        "node_modules",
        "__pycache__",
        ".pytest_cache",
    }

    candidates = [
        path.parent
        for path in workspace_dir.rglob("Dockerfile")
        if not any(part in excluded_dirs for part in path.parts)
    ]

    unique_candidates = list(dict.fromkeys(candidates))

    if len(unique_candidates) == 1:
        return unique_candidates[0]

    if not unique_candidates:
        raise FileNotFoundError(
            "No Dockerfile was found in the cloned repository. "
            "This version of the agent needs a Docker-based test project."
        )

    raise RuntimeError(
        "Multiple Dockerfiles were found. Select the correct test project "
        "before running automated fixes:\n"
        + "\n".join(str(path) for path in unique_candidates)
    )


def find_source_file(project_dir, failure_log):
    """Identify the source file responsible for the first failing test."""
    project_dir = Path(project_dir)

    failed_test = re.search(
        r"FAILED\s+[^:\s]+::(test_[A-Za-z0-9_]+)",
        failure_log,
    )

    if not failed_test:
        raise FileNotFoundError(
            "Could not identify a failed test from the Docker output."
        )

    test_name = failed_test.group(1)
    function_name = test_name.removeprefix("test_")

    matching_files = []

    for path in project_dir.rglob("*.py"):
        if (
            path.name.startswith("test_")
            or path.name == "conftest.py"
            or any(
                part in {
                    ".git",
                    ".venv",
                    "__pycache__",
                    ".pytest_cache",
                }
                for part in path.parts
            )
        ):
            continue

        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        if re.search(
            rf"^\s*def\s+{re.escape(function_name)}\s*\(",
            source,
            re.MULTILINE,
        ):
            matching_files.append(path)

    if len(matching_files) == 1:
        return matching_files[0]

    if not matching_files:
        raise FileNotFoundError(
            f"No source file found defining function '{function_name}'."
        )

    raise RuntimeError(
        f"Multiple source files define '{function_name}'. "
        "Cannot safely select a file automatically:\n"
        + "\n".join(str(path) for path in matching_files)
    )


def main():
    try:
        repository_url = input(
            "Enter the GitHub repository URL: "
        ).strip()

        if not repository_url:
            print("Repository URL cannot be empty.")
            return

        print("\nSTEP 1: Download failed GitHub Actions logs")

        try:
            downloaded_logs = download_failed_workflow_logs(
                repository_url,
                limit=1,
            )
        except (
            ValueError,
            RuntimeError,
            OSError,
            subprocess.TimeoutExpired,
        ) as error:
            print(f"Could not download workflow logs: {error}")
            return

        if not downloaded_logs:
            print(
                "No usable failed workflow logs were downloaded. "
                "Cannot start an evidence-based repair."
            )
            return

        selected = downloaded_logs[0]
        run_info = selected["run"]
        github_log_path = Path(selected["log_path"])

        print(f"\nSelected workflow: {run_info['name']}")
        print(f"Run URL: {run_info['url']}")
        print(f"GitHub log: {github_log_path}")

        if not github_log_path.is_file():
            print("The downloaded workflow log file does not exist.")
            return

        print("\nSTEP 2: Clone or reuse repository")

        try:
            source_dir = clone_repository(repository_url)

            if source_dir is None:
                print("Repository cloning failed. Cannot continue.")
                return

        except (ValueError, RuntimeError, OSError) as error:
            print(f"Repository cloning failed: {error}")
            return

        print("\nSTEP 3: Create isolated workspace")

        try:
            workspace_dir = create_workspace(source_dir)

            if workspace_dir is None:
                print("Workspace creation failed. Cannot continue.")
                return

            workspace_dir = Path(workspace_dir)
            project_dir = find_test_project(workspace_dir)

        except (
            FileNotFoundError,
            RuntimeError,
            OSError,
            ValueError,
            TypeError,
        ) as error:
            print(f"Workspace or project detection failed: {error}")
            return

        print(f"\nSelected test project: {project_dir}")

        run_id = run_info.get(
            "databaseId",
            run_info.get("id", "unknown"),
        )
        remote_failure_copy = (
            LOG_DIR / f"selected_workflow_{run_id}.txt"
        )

        try:
            remote_failure_copy.write_text(
                github_log_path.read_text(
                    encoding="utf-8-sig",
                    errors="replace",
                ),
                encoding="utf-8",
            )
        except OSError as error:
            print(f"Could not preserve the workflow log: {error}")
            return

        print("\nSTEP 4: Reproduce the failure in Docker")

        status, _ = run_docker_tests(
            project_dir,
            "ci-agent-repair-baseline",
            "baseline_test_results.log",
        )

        if status == "passed":
            print("\nSUCCESS: Baseline tests already pass.")
            return

        if status == "infrastructure_error":
            print(
                "Docker could not reliably execute the tests. "
                "Stopping instead of attempting automated fixes."
            )
            return

        latest_log = LOG_DIR / "baseline_test_results.log"

        try:
            failure_text = latest_log.read_text(
                encoding="utf-8",
                errors="replace",
            )
            source_file = find_source_file(
                project_dir,
                failure_text,
            )

        except (
            FileNotFoundError,
            OSError,
            ValueError,
            RuntimeError,
        ) as error:
            print(f"Could not select source file: {error}")
            return

        print(f"\nSource file selected for repair: {source_file}")
        print("\nSTEP 5: Start unlimited fix-and-test loop")
        print(
            "The agent continues until tests pass or an "
            "operational issue occurs."
        )
        print("Press Ctrl+C to stop manually.")

        attempt = 1

        while True:
            print(f"\n{'=' * 50}")
            print(f"FIX ATTEMPT {attempt}")
            print(f"{'=' * 50}")

            try:
                fix_result = generate_fix(
                    source_file,
                    latest_log,
                    attempt,
                )
            except Exception as error:
                print(f"AI fix generation failed: {error}")
                print(
                    "Stopping because the repair could not continue."
                )
                return

            if fix_result == "invalid_code":
                latest_log = (
                    LOG_DIR
                    / f"ai_syntax_error_attempt_{attempt}.log"
                )
                attempt += 1
                continue

            if not fix_result:
                print(
                    "The AI did not produce a usable fix. "
                    "Stopping because the repair cannot continue reliably."
                )
                return

            status, _ = run_docker_tests(
                project_dir,
                f"ci-agent-repair-attempt-{attempt}",
                f"attempt_{attempt}_test_results.log",
            )

            if status == "passed":
                print(
                    f"\nSUCCESS: All tests passed on attempt {attempt}."
                )
                print(f"Verified candidate: {source_file}")
                print("The original GitHub repository was not modified.")
                print("Review the workspace changes before creating a PR.")
                return

            if status == "infrastructure_error":
                print(
                    "Docker could not reliably execute the tests. "
                    "Stopping instead of repeatedly rewriting code."
                )
                return

            latest_log = (
                LOG_DIR / f"attempt_{attempt}_test_results.log"
            )

            try:
                failure_text = latest_log.read_text(
                    encoding="utf-8",
                    errors="replace",
                )

                source_file = find_source_file(
                    project_dir,
                    failure_text,
                )

                print(
                    "\nNext source file selected for repair: "
                    f"{source_file}"
                )

            except (
                FileNotFoundError,
                OSError,
                ValueError,
                RuntimeError,
            ) as error:
                print(f"Could not select the next source file: {error}")
                print(
                    "Stopping because the repair cannot continue safely."
                )
                return

            attempt += 1
            print(
                "Tests still fail. The next attempt will use "
                "the updated log and source file."
            )

    finally:
        save_investigation_report()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nAgent stopped manually.")
        print("Review the candidate changes in the workspace.")
