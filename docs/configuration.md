---
icon: lucide/sliders-horizontal
---

# Configuration

## Free-space threshold

One ini option sets how much free space `/dev/shm` needs before the plugin uses it:

```toml
[tool.pytest.ini_options]
shm_min_free_gib = 4
```

The default is `1`.
Set it above your suite's peak usage, which you can watch with `df -h /dev/shm` during a run.
Override it for one run with `-o shm_min_free_gib=8`.

pytest 9's native `[tool.pytest]` table accepts the number as well.

## Turning it off

Export `TMPDIR` to the directory you want, or pass `-o shm_min_free_gib=inf`.

`-p no:shm` works too, but pytest then warns about the unknown `shm_min_free_gib` option if you configured it, and `--strict-config` makes that an error.

## Measuring the difference

Compare a plain `pytest` run with `pytest -o shm_min_free_gib=inf`, which keeps the plugin off.
`--durations 20` shows which tests gained the most.

## Plugin autoloading

pytest loads the plugin through its `pytest11` entry point.
With `PYTEST_DISABLE_PLUGIN_AUTOLOAD` set, pass `-p shm` to load it.
