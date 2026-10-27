import re
import os
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

EXCLUDED_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
}


def save_investigation_report():
    """Generate the investigation report without hiding the main result."""
    try:
        generate_report()
    except Exception as error:
        print(f"Could not generate investigation report: {error}")


def get_failed_tests(test_output):
    """Extract individual failed test identifiers from pytest output."""
    failed = set()

    for line in test_output.splitlines():
        match = re.match(
            r"^\s*FAILED\s+(\S+)",
            line,
        )
        if match:
            failed.add(match.group(1))

        match = re.match(
            r"^\s*ERROR\s+(\S+)",
            line,
        )
        if match:
            failed.add(match.group(1))

    return failed


def run_docker_tests(project_dir, image_name, log_name):
    """Build and test a project inside Docker only."""
    project_dir = Path(project_dir).resolve()
    log_file = LOG_DIR / log_name
    log_file.parent.mkdir(parents=True, exist_ok=True)

    if not (project_dir / "Dockerfile").is_file():
        message = f"Dockerfile not found in {project_dir}"
        log_file.write_text(message, encoding="utf-8")
        print(message)
        return "infrastructure_error", message

    print("\nBuilding Docker image...")

    try:
        build_result = subprocess.run(
            ["docker", "build", "-t", image_name, str(project_dir)],
            cwd=project_dir,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
        )
    except subprocess.TimeoutExpired:
        message = "Docker image build timed out."
        log_file.write_text(message, encoding="utf-8")
        print(message)
        return "infrastructure_error", message
    except (FileNotFoundError, OSError) as error:
        message = f"Docker could not start: {error}"
        log_file.write_text(message, encoding="utf-8")
        print(message)
        return "infrastructure_error", message

    build_output = (
        (build_result.stdout or "")
        + "\n"
        + (build_result.stderr or "")
    )

    if build_result.returncode != 0:
        log_file.write_text(build_output, encoding="utf-8")
        print(build_output)
        return "infrastructure_error", build_output

    print("\nRunning tests inside Docker...")

    try:
        test_result = subprocess.run(
            ["docker", "run", "--rm", image_name],
            cwd=project_dir,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
        )
    except subprocess.TimeoutExpired:
        message = "Docker tests timed out."
        log_file.write_text(message, encoding="utf-8")
        print(message)
        return "infrastructure_error", message
    except (FileNotFoundError, OSError) as error:
        message = f"Docker tests could not start: {error}"
        log_file.write_text(message, encoding="utf-8")
        print(message)
        return "infrastructure_error", message

    output = (
        (test_result.stdout or "")
        + "\n"
        + (test_result.stderr or "")
    )

    log_file.write_text(output, encoding="utf-8")
    print(output)

    if test_result.returncode == 0:
        return "passed", output

    if re.search(
        r"\bFAILED\b|\bERROR\b|\b\d+\s+failed\b|AssertionError",
        output,
        re.IGNORECASE,
    ):
        return "test_failed", output

    return "infrastructure_error", output


def run_project_tests(project_dir, image_name, log_name):
    """Run tests in Docker; never fall back to host execution."""
    project_dir = Path(project_dir).resolve()

    if not (project_dir / "Dockerfile").is_file():
        message = (
            f"Dockerfile not found in {project_dir}. "
            "Refusing to run tests directly on the host."
        )
        print(message)

        log_file = LOG_DIR / log_name
        log_file.parent.mkdir(parents=True, exist_ok=True)
        log_file.write_text(message + "\n", encoding="utf-8")

        return "infrastructure_error", message

    return run_docker_tests(project_dir, image_name, log_name)


def find_test_project(workspace_dir):
    """Find a supported Docker-based test project."""
    workspace_dir = Path(workspace_dir).resolve()

    def is_excluded(path):
        return any(part in EXCLUDED_DIRS for part in path.parts)

    def is_test_project(path):
        path = Path(path)

        # A Dockerfile is necessary for this Docker-only runner.
        if not (path / "Dockerfile").is_file():
            return False

        has_source = any(
            item.is_file()
            and item.suffix == ".py"
            and not item.name.startswith("test_")
            and item.name != "conftest.py"
            for item in path.glob("*.py")
        )

        if not has_source:
            has_source = any(
                item.is_file()
                and item.suffix == ".py"
                and not item.name.startswith("test_")
                and item.name != "conftest.py"
                for item in path.glob("*/*.py")
            )

        has_tests = (
            (path / "tests").is_dir()
            and any((path / "tests").glob("test_*.py"))
        ) or any(path.glob("test_*.py"))

        return has_source and has_tests

    if is_test_project(workspace_dir):
        return workspace_dir

    preferred = workspace_dir / "sample_project"
    if is_test_project(preferred):
        return preferred

    candidates = []

    for path in workspace_dir.rglob("*"):
        if not path.is_dir():
            continue

        if is_excluded(path.relative_to(workspace_dir)):
            continue

        if is_test_project(path):
            candidates.append(path)

    # Prefer the deepest project directories to avoid selecting
    # a parent directory containing multiple unrelated projects.
    candidates = [
        path
        for path in candidates
        if not any(
            other != path and other in path.parents
            for other in candidates
        )
    ]

    if len(candidates) == 1:
        return candidates[0]

    if not candidates:
        raise FileNotFoundError(
            "No Docker-based Python test project was found. "
            "Expected a Dockerfile, Python source files, and pytest tests."
        )

    raise RuntimeError(
        "Multiple Docker test projects were found. "
        "Please select the correct project:\n"
        + "\n".join(str(path) for path in candidates)
    )


def find_source_file(project_dir, failure_log):
    """Select a likely implementation file from failure evidence."""
    project_dir = Path(project_dir).resolve()
    normalized_log = failure_log.replace("\\", "/")

    failed_test = re.search(
        r"FAILED\s+([^\s:]+)::(test_[A-Za-z0-9_]+)",
        failure_log,
    )

    if failed_test:
        test_path = failed_test.group(1)
        test_name = failed_test.group(2)
    else:
        test_name_match = re.search(
            r"(test_[A-Za-z0-9_]+)",
            failure_log,
        )

        if not test_name_match:
            raise FileNotFoundError(
                "Could not identify failed tests from the test output."
            )

        test_path = None
        test_name = test_name_match.group(1)

    source_files = []

    for path in project_dir.rglob("*.py"):
        relative = path.relative_to(project_dir)

        if any(part in EXCLUDED_DIRS for part in relative.parts):
            continue

        if path.name.startswith("test_") or path.name == "conftest.py":
            continue

        source_files.append(path)

    if not source_files:
        raise FileNotFoundError(
            "No implementation Python files were found."
        )

    source_text = {}

    for path in source_files:
        try:
            source_text[path] = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            source_text[path] = ""

    test_name_lower = test_name.lower()

    # Duplicate-user validation normally belongs to the service layer.
    if "duplicate_user" in test_name_lower:
        service_matches = [
            path for path in source_files if path.stem == "service"
        ]

        if len(service_matches) == 1:
            return service_matches[0]

    # Match a test name to a function, if possible.
    function_name = test_name.removeprefix("test_")

    matching_files = [
        path
        for path, content in source_text.items()
        if re.search(
            rf"^\s*(?:async\s+)?def\s+{re.escape(function_name)}\s*\(",
            content,
            re.MULTILINE,
        )
    ]

    if len(matching_files) == 1:
        return matching_files[0]

    # Inspect traceback references.
    traceback_matches = []

    for path in source_files:
        relative = path.relative_to(project_dir).as_posix()

        path_mentioned = (
            relative in normalized_log or path.name in failure_log
        )

        has_frame = re.search(
            rf'File ["\'][^"\']*{re.escape(path.name)}["\']',
            failure_log,
        )

        if path_mentioned and has_frame:
            traceback_matches.append(path)

    if len(traceback_matches) == 1:
        return traceback_matches[0]

    # Read the failed test and its fixtures to identify imports.
    test_files = []

    if test_path:
        normalized_test_path = test_path.lstrip("./")
        test_files.extend([
            project_dir / normalized_test_path,
            project_dir / "tests" / Path(normalized_test_path).name,
        ])

    tests_dir = project_dir / "tests"

    if tests_dir.is_dir():
        test_files.extend(tests_dir.glob("conftest.py"))

    test_files.append(project_dir / "conftest.py")

    imported_modules = set()

    for test_file in dict.fromkeys(test_files):
        if not test_file.is_file():
            continue

        try:
            test_source = test_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        for package, member in re.findall(
            r"^\s*from\s+([A-Za-z_][\w.]*)\s+import\s+([A-Za-z_]\w*)",
            test_source,
            re.MULTILINE,
        ):
            imported_modules.add(f"{package}.{member}")

        for imported in re.findall(
            r"^\s*import\s+([A-Za-z_][\w.]*)",
            test_source,
            re.MULTILINE,
        ):
            imported_modules.add(imported)

    def module_name(path):
        return ".".join(
            path.relative_to(project_dir).with_suffix("").parts
        )

    direct_matches = {
        path
        for path in source_files
        if any(
            module_name(path) == imported
            or module_name(path).endswith("." + imported)
            or imported.endswith("." + module_name(path))
            for imported in imported_modules
        )
    }

    related_matches = set(direct_matches)

    for path in direct_matches:
        content = source_text.get(path, "")

        dependencies = set(re.findall(
            r"^\s*from\s+([A-Za-z_][\w.]*)\s+import",
            content,
            re.MULTILINE,
        ))

        dependencies.update(re.findall(
            r"^\s*import\s+([A-Za-z_][\w.]*)",
            content,
            re.MULTILINE,
        ))

        for candidate in source_files:
            candidate_module = module_name(candidate)

            if any(
                candidate_module == dependency
                or candidate_module.endswith("." + dependency)
                or dependency.endswith("." + candidate_module)
                for dependency in dependencies
            ):
                related_matches.add(candidate)

    if len(direct_matches) == 1:
        selected = next(iter(direct_matches))
        dependencies = related_matches - direct_matches
        failure_lower = failure_log.lower()

        boundary_failure = any(
            marker in failure_lower
            for marker in (
                "status_code",
                "assert ",
                "expected",
                "got ",
                "response",
            )
        )

        if boundary_failure and len(dependencies) == 1:
            return next(iter(dependencies))

        return selected

    if len(related_matches) == 1:
        return next(iter(related_matches))

    if len(source_files) == 1:
        return source_files[0]

    candidate_list = sorted(
        str(path.relative_to(project_dir))
        for path in (
            related_matches if related_matches else set(source_files)
        )
    )

    raise RuntimeError(
        f"Could not safely select a source file for '{test_name}'. "
        "Multiple files may be responsible:\n"
        + "\n".join(candidate_list)
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

            workspace_dir = Path(workspace_dir).resolve()
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
        print(f"Dockerfile: {project_dir / 'Dockerfile'}")

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

        print("\nSTEP 4: Reproduce the failure inside Docker")

        status, baseline_output = run_project_tests(
            project_dir,
            "ci-agent-repair-baseline",
            "baseline_test_results.log",
        )

        if status == "passed":
            print("\nSUCCESS: Baseline tests already pass.")
            return

        if status == "infrastructure_error":
            print(
                "The test runner could not reliably execute the tests. "
                "Stopping without attempting code changes."
            )
            return

        latest_log = LOG_DIR / "baseline_test_results.log"
        original_failure_log = latest_log

        previous_failed_tests = get_failed_tests(
            latest_log.read_text(
                encoding="utf-8",
                errors="replace",
            )
        )

        try:
            source_file = find_source_file(
                project_dir,
                baseline_output,
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
        print("\nSTEP 5: Start fix-and-test loop")
        print(
            "The agent continues until tests pass or an operational "
            "issue occurs. Press Ctrl+C to stop manually."
        )

        attempt = 1

        while True:
            print(f"\n{'=' * 50}")
            print(f"FIX ATTEMPT {attempt}")
            print(f"{'=' * 50}")

            try:
                previous_code = source_file.read_text(
                    encoding="utf-8"
                )
            except (OSError, UnicodeDecodeError) as error:
                print(f"Could not read source file: {error}")
                return

            try:
                fix_result = generate_fix(
                    source_file,
                    latest_log,
                    attempt,
                )
            except Exception as error:
                print(f"AI fix generation failed: {error}")
                print("Stopping because repair could not continue.")
                return

            if fix_result == "invalid_code":
                print(f"Attempt {attempt} rejected: Ollama generated invalid Python. "
                    "Docker tests were not run for this attempt.")
                syntax_log = (
                    LOG_DIR / f"ai_syntax_error_attempt_{attempt}.log"
                )

                if syntax_log.is_file():
                    syntax_details = syntax_log.read_text(
                        encoding="utf-8",
                        errors="replace",
                    )

                    combined_log = (
                        LOG_DIR / f"attempt_{attempt}_combined_error.log"
                    )

                    previous_failure = latest_log.read_text(
                        encoding="utf-8",
                        errors="replace",
                    )

                    combined_log.write_text(
                        "LATEST FAILURE CONTEXT:\n"
                        + previous_failure[-12000:]
                        + "\n\nSYNTAX ERROR FROM THE LATEST ATTEMPT:\n"
                        + syntax_details[-4000:],
                        encoding="utf-8",
                    )

                    latest_log = combined_log

                attempt += 1
                continue

            if not fix_result:
                print("The AI did not produce a usable fix.")
                return

            status, test_output = run_project_tests(
                project_dir,
                f"ci-agent-repair-attempt-{attempt}",
                f"attempt_{attempt}_test_results.log",
            )

            if status == "passed":
                print(
                    f"\nSUCCESS: All tests passed on attempt {attempt}."
                )
                print(f"Verified candidate: {source_file}")
                print(
                    "The original GitHub repository was not modified."
                )
                return


            if status == "infrastructure_error":
                print("Test infrastructure failed. Stopping safely.")
                try:
                    source_file.write_text(previous_code, encoding="utf-8")
                    print("Previous source code restored.")
                except OSError as error:
                    print(f"CRITICAL: Could not restore source file: {error}")
                    print(f"Check this file immediately: {source_file}")
                return

            current_failed_tests = get_failed_tests(test_output)

            if not current_failed_tests and status != "passed":
                print(
                    "Could not identify failed tests from the test output."
                )
                print("Restoring the previous source code safely.")

                try:
                    source_file.write_text(previous_code, encoding="utf-8")
                except OSError as error:
                    print(f"CRITICAL: Could not restore source file: {error}")
                    print(f"Check this file immediately: {source_file}")

                return

            fixed_tests = previous_failed_tests - current_failed_tests
            new_failures = current_failed_tests - previous_failed_tests

            candidate_state = (
                str(source_file.resolve()),
                tuple(sorted(current_failed_tests)),
                previous_code,
            )

            if fixed_tests and not new_failures:
                previous_failed_tests = current_failed_tests
                latest_log = LOG_DIR / f"attempt_{attempt}_test_results.log"
                print(f"Improvement: fixed {len(fixed_tests)} test(s).")
                print("Keeping this improved candidate.")
            else:
                try:
                    source_file.write_text(previous_code, encoding="utf-8")
                    print("Candidate rejected; previous source restored.")
                except OSError as error:
                    print(f"CRITICAL: Could not restore source file: {error}")
                    print(f"Check this file immediately: {source_file}")
                    return

                if new_failures:
                    print("Regression detected. Newly failing tests:")
                    for test_name in sorted(new_failures):
                        print(f"  - {test_name}")
                else:
                    print("No new tests were fixed in this attempt.")

                latest_log = LOG_DIR / f"attempt_{attempt}_test_results.log"

            try:
                selection_log = (
                    latest_log.read_text(encoding="utf-8", errors="replace")
                    if latest_log.exists()
                    else test_output
                )

                source_file = find_source_file(project_dir, selection_log)
                print(f"Next source file selected: {source_file}")
            except (
                FileNotFoundError,
                OSError,
                RuntimeError,
                ValueError,
            ) as error:
                print(f"Could not select the next source file: {error}")
                return



            attempt += 1
            previous_candidate_state = None
            repeated_candidate_count = 0
            print("Tests still fail. Continuing with the next attempt.")

    finally:
        save_investigation_report()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nAgent stopped manually.")
        print(
            "Review the workspace carefully before accepting any changes."
        )
