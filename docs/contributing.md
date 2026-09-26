---
icon: lucide/git-pull-request
---

# Contributing

## Development

```bash
just install  # uv sync --dev
just test     # uv run pytest -n auto
just lint     # ruff, mypy, ty
just docs     # serve this site locally
```

## Tests

The tests run real pytest sessions in subprocesses with `pytester` and inspect what they leave behind on `/dev/shm`.
They avoid `runpytest_subprocess`, which always passes `--basetemp` and would hide the cleanup of pytest-owned base directories.
Tests that need a usable `/dev/shm` skip elsewhere, so macOS runs only the platform-independent ones.

CI runs the suite on Linux and macOS across Python 3.10 to 3.14, plus one job with pytest 8.4.0, the oldest supported version.

## Releases

Create a GitHub release with a `vX.Y.Z` tag, and the release workflow publishes it to PyPI through trusted publishing.
