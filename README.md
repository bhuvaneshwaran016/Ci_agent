# Autonomous AI Bug-Fixing Agent

An AI-powered software debugging project that detects test failures, investigates errors, generates code corrections using a locally hosted Ollama model, and validates proposed fixes inside Docker.

## Features

- Automated Python testing with pytest inside Docker.
- AI-generated code corrections using Ollama.
- Python syntax validation before applying a proposed fix.
- Isolated workspace to protect the original sample project.
- Backups of previous candidate code.
- Unlimited repair-and-test attempts until tests pass or an operational error occurs.
- Logs of original failures and repair attempts.
- Investigation report generation.

## Technology Stack

- Python
- Ollama
- Docker
- pytest
- uv

## Project Structure

```text
CI_Agent/
├── main.py
├── ai_investigator.py
├── fix_generator.py
├── workspace_manager.py
├── report_generator.py
├── sample_project/
│   ├── app.py
│   ├── test_app.py
│   └── Dockerfile
├── pyproject.toml
├── uv.lock
└── README.md
```

## Prerequisites

- Python 3.12
- Docker Desktop
- uv
- Ollama with the configured local model

## Run Locally

1. Start Docker Desktop.
2. Start Ollama and ensure the configured model is available.
3. Install project dependencies:

   ```powershell
   uv sync
   ```

4. Run the agent:

   ```powershell
   uv run main.py
   ```

5. Generate an investigation report:

   ```powershell
   uv run report_generator.py
   ```

## Safety

The agent tests proposed corrections in an isolated workspace. Review all generated code before using it in a real project.

## Current Status

The prototype has successfully corrected sample syntax and logic errors and verified the resulting code using Docker-based pytest tests.

GitHub Actions integration is planned as a next development step.