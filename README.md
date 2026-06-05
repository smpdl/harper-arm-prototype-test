This is a hardware test for the Harper arm prototype. To set this up, make sure you have Python 3.12+ and [uv](https://docs.astral.sh/uv/). Sync all the packages first:

```bash
uv sync
```

Run commands from the repository root; config paths like `config/arm.yaml` are relative to the current working directory.

Edit `config/arm.yaml` with your serial port, baud rate, and per-joint IDs/models/limits before connecting hardware. Supported motor models: `xc330-m288-t`, `xl430-w250-t`, `xm430-w350-t`, `xm540-w270-t`. The `current_limit` field is used for software safety thresholds and thermal test targets; it is not written to the motor EEPROM.

Edit `config/motions.yaml` to define named poses (e.g. `home`) used by structural tests. Each pose must include every joint from `arm.yaml` with tick values within that joint's `position_limits`.

Launch the Textual TUI to browse suites, configure a test, and run it:

```bash
uv run test
```

Use up/down to pick a test, fill in the options on the right, then press `r` or click Run Test. Press `s` for config/motions/results paths. Payload and point-load tests require `interactive=True` and are intended for direct `run()` calls with stdin, not the TUI.

You can also call suite `run()` functions directly:

```bash
# Motor suite (single joint)
uv run python -c "from suites.motor.ping import run; run(joint='r_sh_flex')"

# Structural suite (all joints)
uv run python -c "from suites.structural.self_weight_hold import run; run()"
```

Results are written to `results/` as timestamped folders (`metadata.json`, `summary.json`, `data.csv`).

Core library lives in `src/harper_arm/` (`config`, `arm`/`motor` control, `safety`, `sampling`, `logging`). The Textual TUI and test catalog live in `tui/`. Test implementations live in `suites/`.
