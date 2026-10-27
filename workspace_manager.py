import shutil
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
WORKSPACE_DIR = BASE_DIR / "workspace"

EXCLUDED_ITEMS = (
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".venv",
    "venv",
    "node_modules",
)


def generate_dockerfile(project_dir):
    """Generate a Dockerfile for a supported Python/pytest project."""
    project_dir = Path(project_dir).resolve()
    dockerfile = project_dir / "Dockerfile"

    # Preserve a Dockerfile supplied by the repository.
    if dockerfile.is_file():
        print("Existing Dockerfile found. Keeping it.")
        return dockerfile

    requirements_file = project_dir / "requirements.txt"

    if requirements_file.is_file():
        install_dependencies = (
            "COPY requirements.txt .\n"
            "RUN pip install --no-cache-dir -r requirements.txt"
        )
    else:
        install_dependencies = (
            "RUN pip install --no-cache-dir pytest"
        )

    # This generator currently supports Python projects using pytest.
    has_python_source = any(
        path.is_file()
        and path.suffix == ".py"
        and not path.name.startswith("test_")
        and path.name != "conftest.py"
        for path in project_dir.rglob("*.py")
        if not any(part in EXCLUDED_ITEMS for part in path.parts)
    )

    has_tests = (
        (project_dir / "tests").is_dir()
        and any((project_dir / "tests").glob("test_*.py"))
    ) or any(project_dir.glob("test_*.py"))

    if not has_python_source or not has_tests:
        raise ValueError(
            "Cannot automatically generate a Dockerfile: "
            "a supported Python source-and-pytest project was not found."
        )

    dockerfile_content = f"""FROM python:3.12-slim

WORKDIR /app

{install_dependencies}

COPY . .

ENV PYTHONPATH=/app

CMD ["python", "-m", "pytest", "-v"]
"""

    dockerfile.write_text(
        dockerfile_content,
        encoding="utf-8",
    )

    print(f"Dockerfile generated automatically: {dockerfile}")
    return dockerfile


def create_workspace(source_dir):
    """Create an isolated workspace and prepare its Docker environment."""
    source_dir = Path(source_dir).resolve()
    workspace_dir = WORKSPACE_DIR.resolve()

    if not source_dir.is_dir():
        raise FileNotFoundError(
            f"Source project not found: {source_dir}"
        )

    # Prevent destructive copying into the source or its own descendants.
    if (
        source_dir == workspace_dir
        or workspace_dir in source_dir.parents
    ):
        raise ValueError(
            "Source project cannot be the workspace or a directory "
            "inside the workspace."
        )

    if workspace_dir.exists():
        shutil.rmtree(workspace_dir)

    shutil.copytree(
        source_dir,
        workspace_dir,
        ignore=shutil.ignore_patterns(*EXCLUDED_ITEMS),
    )

    print("Separate workspace created successfully!")
    print(f"Source project: {source_dir}")
    print(f"AI workspace: {workspace_dir}")

    # Prepare the Docker environment automatically.
    generate_dockerfile(workspace_dir)

    return workspace_dir


if __name__ == "__main__":
    create_workspace(BASE_DIR / "sample_project")
