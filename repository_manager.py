
from datetime import datetime
from pathlib import Path

from git import Repo, GitCommandError


BASE_DIR = Path(__file__).resolve().parent
REPOSITORY_DIR = BASE_DIR / "repository_source"


def normalize_url(url: str) -> str:
    """Normalize a GitHub URL for comparison."""
    return url.strip().rstrip("/").removesuffix(".git").lower()


def clone_repository(repo_url: str):
    """Reuse a matching clone or create a separate, timestamped clone."""
    repo_url = repo_url.strip().rstrip("/")

    if not repo_url.startswith("https://github.com/"):
        print("Please provide a valid HTTPS GitHub repository URL.")
        return None

    expected_url = normalize_url(repo_url)

    # Reuse the existing clone if it belongs to this repository.
    if REPOSITORY_DIR.is_dir():
        try:
            repo = Repo(REPOSITORY_DIR)

            if (
                not repo.bare
                and "origin" in repo.remotes
                and normalize_url(repo.remotes.origin.url) == expected_url
            ):
                print("Existing repository clone is valid.")
                print(f"Using: {REPOSITORY_DIR}")
                return REPOSITORY_DIR

        except (GitCommandError, OSError, ValueError) as error:
            print(f"Could not reuse the existing clone: {error}")

    # Never delete or overwrite the existing repository or its backup.
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    new_clone_dir = BASE_DIR / f"repository_source_new_{timestamp}"

    try:
        print(f"\nCloning repository: {repo_url}")

        Repo.clone_from(
            repo_url + ".git",
            new_clone_dir,
            depth=1,
        )

        print("Repository cloned successfully!")
        print(f"Downloaded to: {new_clone_dir}")
        return new_clone_dir

    except (GitCommandError, OSError, ValueError) as error:
        print(f"Repository cloning failed: {error}")
        print("Existing repository folders have been preserved.")
        return None
