
import json
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlparse


BASE_DIR = Path(__file__).parent
LOG_DIR = BASE_DIR / "investigation_logs"


def parse_repository_url(url):
    parsed = urlparse(url.strip().rstrip("/"))

    if parsed.scheme != "https" or parsed.netloc.lower() != "github.com":
        raise ValueError(
            "Enter a URL like https://github.com/owner/repository"
        )

    parts = parsed.path.strip("/").removesuffix(".git").split("/")

    if len(parts) != 2 or not all(parts):
        raise ValueError("Invalid GitHub repository URL.")

    return f"{parts[0]}/{parts[1]}"


def find_github_cli():
    # First check PATH.
    gh = shutil.which("gh")
    if gh:
        return gh

    # Check common Windows installation locations.
    candidates = [
        Path("C:/Program Files/GitHub CLI/gh.exe"),
        Path.home() / "AppData/Local/Programs/GitHub CLI/gh.exe",
    ]

    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)

    return None


def run_command(command):
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
    )


def download_failed_workflow_logs(repository_url, limit=10):
    repo_name = parse_repository_url(repository_url)
    gh = find_github_cli()

    if not gh:
        print("\nGitHub CLI is not installed or could not be found.")
        print("Install it from https://cli.github.com/")
        return []

    # Verify that GitHub CLI can run.
    version = run_command([gh, "--version"])
    if version.returncode != 0:
        print("GitHub CLI could not run:")
        print(version.stderr)
        return

    print(version.stdout.strip().splitlines()[0])

    # Check authentication.
    auth = run_command([gh, "auth", "status"])
    if auth.returncode != 0:
        print("\nGitHub authentication is required.")
        print("Run the following command and complete browser sign-in:")
        print(f'"{gh}" auth login')
        print(auth.stderr or auth.stdout)
        return

    print(f"\nChecking repository: {repo_name}")

    # Retrieve recent failed workflow runs.
    result = run_command([
        gh, "run", "list",
        "--repo", repo_name,
        "--status", "failure",
        "--limit", str(limit),
        "--json", "databaseId,name,headBranch,createdAt,url",
    ])

    if result.returncode != 0:
        print("\nCould not retrieve workflow runs:")
        print(result.stderr)
        return

    try:
        runs = json.loads(result.stdout)
    except json.JSONDecodeError:
        print("GitHub CLI returned unexpected workflow data.")
        return

    if not runs:
        print("No failed workflow runs found.")
        return

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    downloaded = []

    for run in runs:
        run_id = run["databaseId"]

        print(f"\nWorkflow: {run['name']}")
        print(f"Run ID: {run_id}")
        print(f"Branch: {run['headBranch']}")
        print(f"URL: {run['url']}")

        # Retrieve the log text for this run.
        log_result = run_command([
            gh, "run", "view", str(run_id),
            "--repo", repo_name,
            "--log",
        ])

        if log_result.returncode != 0:
            print("Could not retrieve logs:")
            print(log_result.stderr)
            continue

        if not log_result.stdout.strip():
            print("No log text was returned.")
            continue

        output_path = LOG_DIR / f"workflow_{run_id}_logs.txt"
        output_path.write_text(
            log_result.stdout,
            encoding="utf-8",
        )

        print(f"Logs saved to: {output_path}")
        downloaded.append({
        "run": run,
        "log_path": output_path,
    })

    print(f"\nFinished. Saved {len(downloaded)} log file(s).")
    return downloaded


if __name__ == "__main__":
    url = input("Paste the GitHub repository URL: ").strip()

    try:
        download_failed_workflow_logs(url)
    except (ValueError, OSError, subprocess.TimeoutExpired) as error:
        print(f"\nError: {error}")
