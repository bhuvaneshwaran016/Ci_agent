
import shutil
from pathlib import Path

BASE_DIR = Path(__file__).parent
WORKSPACE_DIR = BASE_DIR / "workspace"


def create_workspace(source_dir):
    source_dir = Path(source_dir).resolve()

    # Validate the source project.
    if not source_dir.exists() or not source_dir.is_dir():
        raise FileNotFoundError(
            f"Source project not found: {source_dir}"
        )

    # Prevent copying the workspace into itself.
    if source_dir == WORKSPACE_DIR.resolve():
        raise ValueError(
            "Source project cannot be the workspace itself."
        )

    # Remove the previous workspace.
    if WORKSPACE_DIR.exists():
        shutil.rmtree(WORKSPACE_DIR)

    # Copy the selected project into an isolated workspace.
    shutil.copytree(
        source_dir,
        WORKSPACE_DIR,
        ignore=shutil.ignore_patterns(
            ".git",
            "__pycache__",
            ".pytest_cache",
            ".venv",
            "node_modules",
        ),
    )

    print("Separate workspace created successfully!")
    print(f"Source project: {source_dir}")
    print(f"AI workspace: {WORKSPACE_DIR}")

    return WORKSPACE_DIR


if __name__ == "__main__":
    create_workspace(BASE_DIR / "sample_project")
