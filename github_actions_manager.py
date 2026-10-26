
import os
from urllib.parse import urlparse

from github import Github, GithubException


def parse_repository_url(repository_url):
    """Convert a GitHub URL into owner/repository format."""

    repository_url = repository_url.strip()
    parsed_url = urlparse(repository_url)

    if (
        parsed_url.scheme != "https"
        or parsed_url.netloc.lower() != "github.com"
    ):
        raise ValueError(
            "Enter a valid GitHub HTTPS URL, for example:\n"
            "https://github.com/owner/repository"
        )

    path = parsed_url.path.strip("/")

    if path.endswith(".git"):
        path = path[:-4]

    parts = path.split("/")

    if len(parts) != 2 or not all(parts):
        raise ValueError(
            "URL must be in this format:\n"
            "https://github.com/owner/repository"
        )

    return f"{parts[0]}/{parts[1]}"


def get_failed_workflow_runs(repo_name, limit=10):
    """Find recent failed GitHub Actions workflow runs."""

    token = os.getenv("GITHUB_TOKEN")

    if token:
        github = Github(token)
    else:
        github = Github()

    try:
        repo = github.get_repo(repo_name)

        print(f"\nChecking GitHub Actions: {repo.full_name}")

        failed_runs = []

        for run in repo.get_workflow_runs(status="failure"):
            failed_runs.append({
                "id": run.id,
                "name": run.name,
                "branch": run.head_branch,
                "commit": run.head_sha,
                "created_at": str(run.created_at),
                "url": run.html_url,
                "logs_url": run.logs_url,
            })

            if len(failed_runs) >= limit:
                break

        return failed_runs

    except GithubException as error:
        raise RuntimeError(
            f"GitHub API request failed: "
            f"{error.status} - {error.data}"
        ) from error

    finally:
        github.close()


if __name__ == "__main__":
    repository_url = input(
        "Enter GitHub repository URL: "
    ).strip()

    try:
        repository = parse_repository_url(repository_url)
        failed_runs = get_failed_workflow_runs(repository)

        if not failed_runs:
            print("\nNo failed workflow runs found.")
        else:
            print(f"\nFound {len(failed_runs)} failed workflow run(s).")

            for run in failed_runs:
                print("\n" + "-" * 40)
                print("Workflow:", run["name"])
                print("Run ID:", run["id"])
                print("Branch:", run["branch"])
                print("Commit:", run["commit"])
                print("Created:", run["created_at"])
                print("Run URL:", run["url"])

    except (ValueError, RuntimeError) as error:
        print(f"\nError: {error}")
