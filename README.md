toggl-buttons
=============

This project drives an Arduino-backed button panel and syncs it with Toggl Track only. It does not talk to ActivityWatch.

Behavior:

- Pressing a timer button prompts for a description, stops any currently running Toggl timer, and starts a new one.
- Pressing the `null` button stops the current Toggl timer and clears the LEDs so no timer is running.
- Every 2 minutes the app polls Toggl's current running entry and forces the hardware LEDs back into sync.
- The app avoids extra Toggl reads during normal button presses and backs off hard after API failures to reduce request burn.

Setup
-----

1. Install dependencies:

```sh
uv sync
```

2. Run the watcher once to generate the config:

```sh
uv run toggl-buttons
```

3. Edit the generated config file:

- Windows: `~/AppData/Roaming/toggl-buttons/config.toml`
- Linux/macOS: `~/.config/toggl-buttons/config.toml`

Config notes:

- `toggl_api_token` is your Toggl Track API token.
- `workspace_id` can be left as `0` to use your Toggl default workspace.
- `ports` should contain one or more serial device paths, for example `["COM3"]`.
- `sync_interval_seconds` controls the scheduled Toggl reconciliation interval. Increase it if you want even fewer requests.
- `sync_retry_backoff_seconds` controls how long the app waits after a Toggl API failure before trying another background sync.
- Each `[[toggl_buttons.buttons]]` entry can be:
  - `mode = "timer"` for a real timer button
  - `mode = "null"` for the stop/clear button
- Timer buttons can optionally define `project_id`, `task_id`, `tags`, `workspace_id`, and `description_prefix`.
- Keep exactly one button with `mode = "null"` if you want a dedicated "no timer running" state.

Example timer button:

```toml
[[toggl_buttons.buttons]]
name = "client-a"
mode = "timer"
project_id = 1234567
tags = ["buttons"]
```

Windows auto-start
------------------

If you want the watcher to restart automatically and still be able to show the description prompt, use Task Scheduler instead of a Windows service.

For a visible console-based restarter, use [run_toggl_buttons.cmd](/mnt/c/Users/Zachs/Desktop/Projects/togglButtons/run_toggl_buttons.cmd).

If you want it hidden, use [run_toggl_buttons_hidden.vbs](/mnt/c/Users/Zachs/Desktop/Projects/togglButtons/run_toggl_buttons_hidden.vbs) and point Task Scheduler at that file instead. It launches `.venv\Scripts\pythonw.exe -m toggl_buttons.main`, which avoids the console window entirely.

Recommended Task Scheduler settings:

- Trigger: `At log on`
- Security option: `Run only when user is logged on`
- Start in: the project directory
- Action: start `run_toggl_buttons_hidden.vbs`
- Settings: enable restart on failure, for example every 1 minute up to a large count

Prerequisite for the hidden launcher:

```sh
uv sync
```

That ensures `.venv\Scripts\pythonw.exe` exists.

To stop a running background instance manually:

```powershell
powershell -ExecutionPolicy Bypass -File .\stop_toggl_buttons.ps1
```

Why not a service:

- This app uses `tkinter` prompts for timer descriptions.
- Windows services run in Session 0, so interactive prompts are the wrong fit there.

Arduino
-------

The included [buttons/buttons.ino](/mnt/c/Users/Zachs/Desktop/Projects/togglButtons/buttons/buttons.ino) sketch extends the original `aw-watcher-buttons` firmware with a serial `lN` command:

- `l1` through `l5` set the active LED from software
- `l0` clears all LEDs

That command is what allows the 2-minute Toggl sync to correct the hardware state.

Repository notes
----------------

- This repo is licensed under the MIT License. See [LICENSE](/mnt/c/Users/Zachs/Desktop/Projects/togglButtons/LICENSE).
- Local build artifacts such as `.venv/` and `__pycache__/` are ignored via `.gitignore`.
