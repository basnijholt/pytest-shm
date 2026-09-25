# pytest-shm Development Guidelines

## Core Principles

- **KISS**: Keep it simple. This is one small pytest plugin module.
- **YAGNI**: Don't add features until they're needed. No macOS RAM disks, no per-test cleanup, no configurable mount point.
- **DRY**: Reuse patterns. `off_reason` is the single source of truth for whether `/dev/shm` may be used.

## Architecture

```
src/pytest_shm/
├── __init__.py   # Version only
├── plugin.py     # All hooks, the containment fixture, and off_reason()
└── py.typed
```

The plugin is registered through the `pytest11` entry point `shm = "pytest_shm.plugin"`, so `-p no:shm` disables it.

## Key Design Decisions

1. **Switch before conftests**: `pytest_load_initial_conftests` runs `tryfirst`, before pytest imports any `conftest.py`, so conftests and the modules they import already see `/dev/shm` as the temp root.
2. **Exported temp roots win**: an exported `TMPDIR`, `TEMP`, or `TMP` means the user chose a temp root; the plugin never overrides it.
3. **Containment follows the temp root, not the switch**: the session fixture acts whenever `tempfile.gettempdir()` is `/dev/shm`, because xdist workers inherit the controller's `TMPDIR` and never switch themselves.
4. **Per-worker cleanup**: each process deletes the base directory pytest chose for it after a passing session. xdist gives every worker `--basetemp`, so the controller passes `shm_owns_basetemp` through `workerinput` to say whether the caller chose one.
5. **No per-test deletion**: pytest reuses freed numbered directory names, and path-keyed caches then leak state between tests.
6. **Restore on unconfigure**: in-process sessions (`pytest.main()`, `pytester.runpytest_inprocess()`) get their original environment back.

## Development Commands

Use `just` for common tasks. Run `just` to list available commands:

| Command | Description |
|---------|-------------|
| `just install` | Install dev dependencies |
| `just test` | Run all tests (parallel) |
| `just lint` | Lint, format, and type check |
| `just clean` | Clean build artifacts |

## Testing

Tests in `tests/test_plugin.py` start real pytest sessions with `pytester.run(sys.executable, "-m", "pytest", ...)`.
`runpytest_subprocess` is avoided because it always passes `--basetemp`, which hides the pytest-owned cleanup path.
The `temproot` fixture removes exported temp roots and points `PYTEST_DEBUG_TEMPROOT` at a fresh directory on `/dev/shm`, so each inner session's base directories are isolated and can be inspected afterwards.
Tests that need a usable `/dev/shm` are marked `needs_shm` and skip elsewhere.

## Communication Notes

- Clarify ambiguous wording (e.g., homophones like "right"/"write", "their"/"there").

## Git Safety

- Never amend commits.
- **NEVER merge anything into main.** Always commit directly or use fast-forward/rebase.
- Never force push.

## Pull Requests

- Never include unchecked checklists (e.g., `- [ ] ...`) in PR descriptions. Either omit the checklist or use checked items.
- **NEVER run `gh pr merge`**. PRs are merged via the GitHub UI, not the CLI.

## Releases

Use `gh release create` to create releases. The tag is created automatically, and `release.yml` publishes to PyPI through trusted publishing.

```bash
# IMPORTANT: Ensure you're on latest origin/main before releasing!
git fetch origin
git checkout origin/main

# Check current version
git tag --sort=-v:refname | head -1

# Create release (minor version bump: v0.1.0 -> v0.2.0)
gh release create v0.2.0 --title "v0.2.0" --notes "release notes here"
```

Versioning:
- **Patch** (v0.1.0 → v0.1.1): Bug fixes
- **Minor** (v0.1.1 → v0.2.0): New features, non-breaking changes

Write release notes manually describing what changed. Group by features and bug fixes.
