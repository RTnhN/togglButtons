#!/usr/bin/env bash

set -euo pipefail

app_name="toggl-buttons"
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
venv_python="${script_dir}/.venv/bin/python"
config_root="${XDG_CONFIG_HOME:-${HOME}/.config}"
service_dir="${config_root}/systemd/user"
service_path="${service_dir}/${app_name}.service"

escape_systemd_value() {
    local value="$1"
    value="${value//\\/\\\\}"
    value="${value//\"/\\\"}"
    value="${value//%/%%}"
    value="${value//\$/\$\$}"
    printf '%s' "${value}"
}

if [[ "${1:-}" == "--remove" ]]; then
    systemctl --user disable --now "${app_name}.service" 2>/dev/null || true
    if [[ -f "${service_path}" ]]; then
        rm -- "${service_path}"
    fi
    systemctl --user daemon-reload
    echo "Removed the ${app_name} Linux auto-start service."
    exit 0
fi

if [[ $# -ne 0 ]]; then
    echo "Usage: $0 [--remove]" >&2
    exit 2
fi

if [[ "$(uname -s)" != "Linux" ]]; then
    echo "This installer only supports Linux." >&2
    exit 1
fi

if ! command -v uv >/dev/null 2>&1; then
    echo "uv is required. Install it, then run this script again." >&2
    exit 1
fi

if ! command -v systemctl >/dev/null 2>&1; then
    echo "systemd is required for Linux auto-start." >&2
    exit 1
fi

echo "Installing project dependencies..."
uv sync --project "${script_dir}"

if ! "${venv_python}" -c "import tkinter, serial" >/dev/null 2>&1; then
    echo "Python's tkinter support is required for the description prompt." >&2
    echo "Install your distribution's Tk package (often python3-tk), then try again." >&2
    exit 1
fi

"${venv_python}" -c "from toggl_buttons.main import ensure_config; ensure_config()"
config_path="$("${venv_python}" -c "from toggl_buttons.main import get_config_path; print(get_config_path())")"

if ! "${venv_python}" - "${config_path}" <<'PY'
import sys
import tomllib

with open(sys.argv[1], "rb") as config_file:
    settings = tomllib.load(config_file).get("toggl_buttons", {})

configured = bool(
    str(settings.get("toggl_api_token") or "").strip()
    and settings.get("buttons")
)
raise SystemExit(0 if configured else 1)
PY
then
    echo "Config needs setup: ${config_path}" >&2
    echo "Set toggl_api_token there, then run this installer again." >&2
    exit 1
fi

mkdir -p -- "${service_dir}"
escaped_script_dir="$(escape_systemd_value "${script_dir}")"
escaped_venv_python="$(escape_systemd_value "${venv_python}")"
{
    printf '%s\n' \
        "[Unit]" \
        "Description=Toggl physical button watcher" \
        "Wants=network-online.target" \
        "After=network-online.target graphical-session.target" \
        "" \
        "[Service]" \
        "Type=simple" \
        "WorkingDirectory=${escaped_script_dir}" \
        "ExecStart=\"${escaped_venv_python}\" -m toggl_buttons.main" \
        "Restart=on-failure" \
        "RestartSec=5" \
        "Environment=PYTHONUNBUFFERED=1" \
        "" \
        "[Install]" \
        "WantedBy=default.target"
} >"${service_path}"

systemctl --user daemon-reload
systemctl --user enable "${app_name}.service"
systemctl --user restart "${app_name}.service"

echo
echo "${app_name} is enabled and running. It will start automatically when you log in."
echo "Status: systemctl --user status ${app_name}"
echo "Logs:   journalctl --user -u ${app_name} -f"
echo "Remove: $0 --remove"
