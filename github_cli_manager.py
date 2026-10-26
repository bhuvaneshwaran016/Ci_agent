
import shutil
import subprocess
from pathlib import Path


def find_github_cli():
    # First check whether gh is available through PATH.
    gh_command = shutil.which("gh")

    if gh_command:
        return gh_command

    # Check common Windows installation locations.
    candidates = [
        Path("C:/Program Files/GitHub CLI/gh.exe"),
        Path.home() / "AppData/Local/Programs/GitHub CLI/gh.exe",
    ]

    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)

    return None


def check_github_cli():
    gh_path = find_github_cli()

    if not gh_path:
        print("GitHub CLI is not installed or could not be found.")
        print("Install it from: https://cli.github.com/")
        return False

    try:
        result = subprocess.run(
            [gh_path, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )

        if result.returncode != 0:
            print("GitHub CLI was found but could not run.")
            print(result.stderr)
            return False

        print(result.stdout.strip().splitlines()[0])
        print("GitHub CLI is ready.")
        return True

    except (OSError, subprocess.TimeoutExpired) as error:
        print(f"Could not run GitHub CLI: {error}")
        return False


if __name__ == "__main__":
    check_github_cli()
