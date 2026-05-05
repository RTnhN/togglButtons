#!/usr/bin/env python3

import logging
import sys
import time
import traceback
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
import tkinter as tk
from tkinter import simpledialog

import tomllib

from .buttons import Buttons
from .toggl import TogglAPIError, TogglClient, TimeEntry


APP_NAME = "toggl-buttons"
CONFIG_SECTION = "toggl_buttons"
DESCRIPTION_TIMEOUT_SECONDS = 30
DEFAULT_CONFIG = f"""
[{CONFIG_SECTION}]
poll_time = 0.2
sync_interval_seconds = 120
sync_retry_backoff_seconds = 600
ports = []
toggl_api_token = ""
workspace_id = 0
button_prompt_timeout_seconds = 30

[[{CONFIG_SECTION}.buttons]]
name = "green"
mode = "timer"
project_id = 0
tags = []

[[{CONFIG_SECTION}.buttons]]
name = "red"
mode = "timer"
project_id = 0
tags = []

[[{CONFIG_SECTION}.buttons]]
name = "blue"
mode = "timer"
project_id = 0
tags = []

[[{CONFIG_SECTION}.buttons]]
name = "yellow"
mode = "timer"
project_id = 0
tags = []

[[{CONFIG_SECTION}.buttons]]
name = "null"
mode = "null"
"""

logger = logging.getLogger(APP_NAME)


def get_config_path() -> Path:
    if sys.platform == "win32":
        config_root = Path.home() / "AppData" / "Roaming"
    else:
        config_root = Path.home() / ".config"
    return config_root / APP_NAME / "config.toml"


def ensure_config() -> Path:
    config_path = get_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    if not config_path.exists():
        config_path.write_text(DEFAULT_CONFIG.lstrip(), encoding="utf-8")
    return config_path


def setup_logging() -> Path:
    config_path = ensure_config()
    log_path = config_path.parent / f"{APP_NAME}.log"

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s [%(name)s] %(message)s"
    )

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.handlers.clear()

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=1_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    return log_path


def load_config() -> dict:
    config_path = ensure_config()
    with config_path.open("rb") as config_file:
        return tomllib.load(config_file)


def print_statusline(message: str):
    last_length = len(print_statusline.last_msg) if hasattr(print_statusline, "last_msg") else 0
    print(" " * last_length, end="\r")
    print(message, end="\r")
    print_statusline.last_msg = message


def normalize_ports(ports_value):
    if ports_value is None:
        return []
    if isinstance(ports_value, str):
        return [ports_value] if ports_value else []
    return [port for port in ports_value if port]


def normalize_buttons(buttons_value):
    normalized = []
    for raw in buttons_value or []:
        mode = (raw.get("mode") or "timer").strip().lower()
        normalized.append(
            {
                "name": raw.get("name", "").strip() or f"button-{len(normalized) + 1}",
                "mode": mode,
                "project_id": raw.get("project_id") or None,
                "task_id": raw.get("task_id") or None,
                "tags": list(raw.get("tags") or []),
                "workspace_id": raw.get("workspace_id") or None,
                "description_prefix": (raw.get("description_prefix") or "").strip(),
            }
        )
    return normalized


def find_null_button_index(buttons: list[dict]) -> int | None:
    for index, button in enumerate(buttons, start=1):
        if button["mode"] == "null":
            return index
    return None


def matches_button(entry: TimeEntry, button: dict) -> bool:
    if button["mode"] != "timer":
        return False
    if button["project_id"] is not None and entry.project_id != button["project_id"]:
        return False
    if button["task_id"] is not None and entry.task_id != button["task_id"]:
        return False
    if button["description_prefix"] and not entry.description.startswith(
        button["description_prefix"]
    ):
        return False
    button_tags = set(button["tags"])
    if button_tags and not button_tags.issubset(set(entry.tags)):
        return False
    return True


def resolve_button_state(entry: TimeEntry | None, buttons: list[dict]) -> int:
    if entry is None:
        return -1
    for index, button in enumerate(buttons, start=1):
        if matches_button(entry, button):
            return index
    return -1


def prompt_description(root: tk.Tk, button_label: str, timeout_seconds: int) -> str:
    root.attributes("-topmost", True)
    root.update()

    timeout_handle = {"id": None}

    def close_if_idle():
        timeout_handle["id"] = None
        for child in root.winfo_children():
            if isinstance(child, tk.Toplevel) and child.wm_title() == APP_NAME:
                entry_widget = child.children.get("entry")
                if entry_widget is None or not entry_widget.get().strip():
                    child.destroy()
                break

    timeout_handle["id"] = root.after(int(timeout_seconds * 1000), close_if_idle)
    try:
        description_input = simpledialog.askstring(
            APP_NAME,
            f"Timer description for {button_label}:",
            parent=root,
        )
    finally:
        timeout_id = timeout_handle["id"]
        if timeout_id is not None:
            root.after_cancel(timeout_id)
        root.attributes("-topmost", False)
    return (description_input or "").strip()


def describe_time_entry(entry: TimeEntry | None) -> str:
    if entry is None:
        return "no running timer"

    description = entry.description or "(no description)"
    details = [f"id={entry.id}", f"workspace={entry.workspace_id}", f"description={description!r}"]
    if entry.project_id is not None:
        details.append(f"project={entry.project_id}")
    if entry.task_id is not None:
        details.append(f"task={entry.task_id}")
    if entry.tags:
        details.append(f"tags={entry.tags}")
    return ", ".join(details)


def log_external_timer_change(
    previous_entry: TimeEntry | None,
    current_entry: TimeEntry | None,
    *,
    sync_reason: str,
) -> None:
    previous_id = previous_entry.id if previous_entry is not None else None
    current_id = current_entry.id if current_entry is not None else None
    if previous_id == current_id:
        return

    if previous_entry is not None and current_entry is None:
        logger.warning(
            "Timer stopped outside physical buttons, likely via Toggl Web/UI/app/API (%s): %s",
            sync_reason,
            describe_time_entry(previous_entry),
        )
        return

    if previous_entry is None and current_entry is not None:
        logger.info(
            "Timer started outside physical buttons, likely via Toggl Web/UI/app/API (%s): %s",
            sync_reason,
            describe_time_entry(current_entry),
        )
        return

    if previous_entry is not None and current_entry is not None:
        logger.warning(
            "Timer changed outside physical buttons, likely via Toggl Web/UI/app/API (%s): stopped [%s]; now running [%s]",
            sync_reason,
            describe_time_entry(previous_entry),
            describe_time_entry(current_entry),
        )


def sync_buttons_to_toggl(
    toggl: TogglClient,
    buttons_manager: Buttons,
    buttons: list[dict],
    cached_entry: TimeEntry | None = None,
    sync_reason: str = "periodic sync",
    observed_state: int | None = None,
) -> tuple[TimeEntry | None, int]:
    current_entry = toggl.get_current_time_entry()
    log_external_timer_change(cached_entry, current_entry, sync_reason=sync_reason)
    desired_state = resolve_button_state(current_entry, buttons)
    if observed_state is None:
        observed_state = buttons_manager.led_state
    if buttons_manager.is_connected() and observed_state != desired_state:
        buttons_manager.set_active_led(desired_state)
    return current_entry, desired_state


def stop_cached_time_entry(
    toggl: TogglClient,
    current_entry: TimeEntry | None,
    *,
    reason: str,
) -> None:
    if current_entry is None:
        logger.info("Stop requested (%s), but no cached timer was running.", reason)
        return
    logger.info(
        "Stopping timer via physical buttons (%s): %s",
        reason,
        describe_time_entry(current_entry),
    )
    toggl.stop_time_entry(current_entry.workspace_id, current_entry.id)


def main():
    log_path = setup_logging()
    config_path = ensure_config()
    config = load_config()
    settings = config.get(CONFIG_SECTION, {})
    logger.info("Logging to %s", log_path)

    ports = normalize_ports(settings.get("ports"))
    buttons = normalize_buttons(settings.get("buttons"))
    poll_time = float(settings.get("poll_time", 0.2))
    sync_interval_seconds = int(settings.get("sync_interval_seconds", 120))
    sync_retry_backoff_seconds = int(settings.get("sync_retry_backoff_seconds", 600))
    prompt_timeout_seconds = int(
        settings.get("button_prompt_timeout_seconds", DESCRIPTION_TIMEOUT_SECONDS)
    )
    api_token = (settings.get("toggl_api_token") or "").strip()
    configured_workspace_id = int(settings.get("workspace_id") or 0)

    if not ports or not buttons:
        logger.error("Ports and buttons must be configured in %s", config_path)
        sys.exit(1)

    null_button_index = find_null_button_index(buttons)

    toggl = TogglClient(api_token=api_token, user_agent=APP_NAME)
    workspace_id = configured_workspace_id or toggl.get_default_workspace_id()
    buttons_manager = Buttons(ports)

    root = tk.Tk()
    root.withdraw()

    device_connected = buttons_manager.is_connected()
    previous_state = None
    current_entry = None
    last_sync_at = 0.0
    next_sync_at = 0.0
    blinked = False

    try:
        current_entry, previous_state = sync_buttons_to_toggl(
            toggl,
            buttons_manager,
            buttons,
            cached_entry=current_entry,
            sync_reason="initial sync",
            observed_state=buttons_manager.led_state,
        )
        last_sync_at = time.monotonic()
        next_sync_at = last_sync_at + sync_interval_seconds
    except TogglAPIError as exc:
        logger.error("Initial Toggl sync failed: %s", exc)
        next_sync_at = time.monotonic() + sync_retry_backoff_seconds

    while True:
        try:
            state = buttons_manager.get_led_state()
            currently_connected = buttons_manager.is_connected()
            now = time.monotonic()

            if now >= next_sync_at:
                current_entry, previous_state = sync_buttons_to_toggl(
                    toggl,
                    buttons_manager,
                    buttons,
                    cached_entry=current_entry,
                    sync_reason="periodic sync",
                    observed_state=state,
                )
                last_sync_at = now
                next_sync_at = now + sync_interval_seconds
                time.sleep(poll_time)
                continue

            if not currently_connected:
                if device_connected:
                    print_statusline("Buttons disconnected")
                    previous_state = None
                    blinked = False
                device_connected = False
                time.sleep(poll_time)
                continue

            if not device_connected:
                device_connected = True
                current_entry, previous_state = sync_buttons_to_toggl(
                    toggl,
                    buttons_manager,
                    buttons,
                    cached_entry=current_entry,
                    sync_reason="device reconnect sync",
                    observed_state=state,
                )
                last_sync_at = now
                next_sync_at = now + sync_interval_seconds
                blinked = False
                time.sleep(poll_time)
                continue

            if state != previous_state:
                if not (1 <= state <= len(buttons)):
                    time.sleep(poll_time)
                    continue

                pressed_button = buttons[state - 1]

                if pressed_button["mode"] == "null" and state == null_button_index:
                    stop_cached_time_entry(
                        toggl,
                        current_entry,
                        reason=f"null button '{pressed_button['name']}'",
                    )
                    buttons_manager.set_active_led(-1)
                    current_entry = None
                    previous_state = -1
                    print_statusline("No timer running")
                else:
                    description = prompt_description(
                        root,
                        pressed_button["name"],
                        prompt_timeout_seconds,
                    )
                    stop_cached_time_entry(
                        toggl,
                        current_entry,
                        reason=f"timer button '{pressed_button['name']}' starting a replacement timer",
                    )

                    button_workspace_id = pressed_button["workspace_id"] or workspace_id
                    current_entry = toggl.start_time_entry(
                        workspace_id=button_workspace_id,
                        description=description,
                        created_with=APP_NAME,
                        project_id=pressed_button["project_id"],
                        task_id=pressed_button["task_id"],
                        tags=pressed_button["tags"],
                    )
                    previous_state = state
                    title = description or pressed_button["name"]
                    logger.info(
                        "Started timer via physical button '%s': %s",
                        pressed_button["name"],
                        describe_time_entry(current_entry),
                    )
                    print_statusline(f"Running: {title}")

                last_sync_at = time.monotonic()
                next_sync_at = last_sync_at + sync_interval_seconds

            current_clock = datetime.now()
            if previous_state and previous_state > 0:
                if current_clock.minute % 15 == 0 and current_clock.second == 0:
                    if not blinked:
                        buttons_manager.blink_led(previous_state, 5, 9)
                        blinked = True
                else:
                    blinked = False
            else:
                blinked = False

        except KeyboardInterrupt:
            break
        except TogglAPIError as exc:
            logger.error("Toggl API error: %s", exc)
            previous_state = state if 1 <= state <= len(buttons) else -1
            next_sync_at = time.monotonic() + sync_retry_backoff_seconds
        except Exception as exc:
            print(f"An exception occurred: {exc}")
            traceback.print_exc()
            buttons_manager.close()
            sys.exit(1)

        time.sleep(poll_time)

    buttons_manager.close()


if __name__ == "__main__":
    main()
