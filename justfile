# pytest-shm Development Commands
# Run `just` to see available commands

# Default: list available commands
default:
    @just --list

# Install development dependencies
install:
    uv sync --dev

# Run all tests (parallel)
test:
    uv run pytest -n auto

# Lint, format, and type check
lint:
    uv run ruff check --fix .
    uv run ruff format .
    uv run mypy src tests
    uv run ty check

# Clean up build artifacts and caches
clean:
    rm -rf .pytest_cache .mypy_cache .ruff_cache dist build
    find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
