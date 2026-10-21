
import shutil
from pathlib import Path

# Find the main project directory
BASE_DIR = Path(__file__).parent

# The original project that must remain unchanged
SOURCE_DIR = BASE_DIR / "sample_project"

# The separate copy where the AI can work
WORKSPACE_DIR = BASE_DIR / "workspace"


def create_workspace():
    # Check whether the original project exists
    if not SOURCE_DIR.exists():
        raise FileNotFoundError(
            f"Original project not found: {SOURCE_DIR}"
        )

    # Remove the previous workspace, if it exists
    if WORKSPACE_DIR.exists():
        shutil.rmtree(WORKSPACE_DIR)

    # Copy the original project into a new workspace
    shutil.copytree(
        SOURCE_DIR,
        WORKSPACE_DIR,
        ignore=shutil.ignore_patterns(
            "__pycache__",
            ".pytest_cache",
            ".venv",
        ),
    )

    print("Separate workspace created successfully!")
    print(f"Original project: {SOURCE_DIR}")
    print(f"AI workspace: {WORKSPACE_DIR}")


if __name__ == "__main__":
    create_workspace()
