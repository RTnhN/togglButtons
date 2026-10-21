import logging
import os
import sys
import time

import serial
from serial.tools import list_ports


logger = logging.getLogger(__name__)

# Must match deviceId in buttons/buttons.ino.
DEVICE_ID_PREFIX = "toggl-buttons"
IDENTIFY_COMMAND = "id"
# Opening the port resets most Arduinos, and the bootloader can take ~2s
# before the sketch starts answering.
IDENTIFY_TIMEOUT = 3.5
IDENTIFY_RETRY_INTERVAL = 0.5
# Ports that fail the handshake are probed again after this long.
REJECTED_PORT_RETRY_SECONDS = 60


def _is_candidate_port(info):
    if sys.platform == "win32":
        return True
    if sys.platform == "darwin":
        return info.vid is not None
    # Built-in UARTs (ttyS*) and other tty devices are never the panel.
    return os.path.basename(info.device).startswith(("ttyACM", "ttyUSB"))


def _discard_and_close(connection):
    # Closing a tty waits (up to 30s) for unsent output to drain, which never
    # happens on devices that don't read their input, so drop it first.
    try:
        connection.reset_output_buffer()
    except (serial.SerialException, OSError):
        pass
    connection.close()


class Buttons:
    def __init__(self, baudrate=115200, timeout=1):
        self.port = None
        self.baudrate = baudrate
        self.timeout = timeout
        self.serial = None
        self.led_state = -1
        self._connected = False
        self._warned_not_found = False
        # device -> (hwid, retry_at) for ports that failed the handshake, so
        # other serial devices are not reset by a probe every few seconds.
        self._rejected_ports = {}
        self._last_connect_attempt = 0.0
        self._reconnect_interval = 2.0

        self._ensure_connection(force=True)

    def _cleanup_serial(self):
        if self.serial:
            try:
                self.serial.close()
            except Exception:
                pass
        self.serial = None

    def _mark_connected(self, port):
        if not self._connected or self.port != port:
            logger.info("Connected to button device on %s", port)
        self.port = port
        self._connected = True
        self._warned_not_found = False

    def _candidate_ports(self):
        available = {info.device: info for info in list_ports.comports()}

        now = time.monotonic()
        for device, (hwid, retry_at) in list(self._rejected_ports.items()):
            info = available.get(device)
            if now >= retry_at or (info.hwid if info else None) != hwid:
                del self._rejected_ports[device]

        return [
            device
            for device in sorted(available)
            if _is_candidate_port(available[device])
            and device not in self._rejected_ports
        ], available

    def _identify(self, connection):
        deadline = time.monotonic() + IDENTIFY_TIMEOUT
        next_ping = 0.0
        while time.monotonic() < deadline:
            if time.monotonic() >= next_ping:
                # No flush(): on POSIX it waits for the write to go out with no
                # timeout, which hangs on devices that never read their input.
                connection.write(f"{IDENTIFY_COMMAND}\n".encode())
                next_ping = time.monotonic() + IDENTIFY_RETRY_INTERVAL
            # Cap the read so a device streaming data without newlines can't
            # keep readline() from returning past the deadline.
            response = connection.readline(64).decode(errors="ignore").strip()
            if response.startswith(DEVICE_ID_PREFIX):
                # Drop replies to any extra pings so they are not read as state.
                time.sleep(0.2)
                connection.reset_input_buffer()
                return response
        return None

    def _probe(self, port):
        try:
            connection = serial.Serial(
                port,
                self.baudrate,
                timeout=IDENTIFY_RETRY_INTERVAL,
                write_timeout=IDENTIFY_RETRY_INTERVAL,
                exclusive=True,
            )
        except (serial.SerialException, OSError) as exc:
            logger.debug("Unable to open %s: %s", port, exc)
            return None, False

        try:
            connection.reset_input_buffer()
            connection.reset_output_buffer()
            device_id = self._identify(connection)
        except serial.SerialTimeoutException:
            _discard_and_close(connection)
            return None, True
        except (serial.SerialException, OSError) as exc:
            logger.debug("Error probing %s: %s", port, exc)
            _discard_and_close(connection)
            return None, False

        if device_id is None:
            _discard_and_close(connection)
            return None, True

        connection.timeout = self.timeout
        connection.write_timeout = self.timeout
        logger.info("Found %s on %s", device_id, port)
        return connection, False

    def _connect(self):
        candidates, available = self._candidate_ports()
        for port in candidates:
            connection, wrong_device = self._probe(port)
            if connection is not None:
                self.serial = connection
                self._mark_connected(port)
                return True
            if wrong_device:
                info = available.get(port)
                self._rejected_ports[port] = (
                    info.hwid if info else None,
                    time.monotonic() + REJECTED_PORT_RETRY_SECONDS,
                )
                logger.debug(
                    "%s did not answer the button panel handshake; retrying "
                    "in %ss",
                    port,
                    REJECTED_PORT_RETRY_SECONDS,
                )

        if not self._warned_not_found:
            logger.warning(
                "No button device found; will keep scanning (flash "
                "buttons/buttons.ino if the panel is plugged in)"
            )
            self._warned_not_found = True
        self._connected = False
        return False

    def _ensure_connection(self, force=False):
        if self.serial and self.serial.is_open:
            return True

        now = time.monotonic()
        if not force and (now - self._last_connect_attempt) < self._reconnect_interval:
            return False

        self._connect()
        # Measure from the end of the scan so slow probes don't run back to back.
        self._last_connect_attempt = time.monotonic()
        return self._connected

    def _handle_serial_error(self, exc):
        if self._connected:
            logger.warning("Lost connection to %s: %s", self.port, exc)
        self._cleanup_serial()
        self._connected = False

    def _send_command(self, command):
        if not self._ensure_connection():
            return False

        try:
            self.serial.write(f"{command}\n".encode())
            self.serial.flush()
            time.sleep(0.1)
            return True
        except (serial.SerialException, OSError) as exc:
            logger.warning("Error sending command '%s': %s", command, exc)
            self._handle_serial_error(exc)
            return False

    def update_led_state(self):
        if not self._send_command("state"):
            self.led_state = -1
            return

        try:
            response = self.serial.readline().decode(errors="ignore").strip()
            if response == "-1" or response == "":
                self.led_state = -1
            elif response.isdigit():
                self.led_state = int(response)
            else:
                self.led_state = -1
        except (serial.SerialException, OSError) as exc:
            logger.warning("Error reading button state, will retry: %s", exc)
            self._handle_serial_error(exc)
            self.led_state = -1

    def get_led_state(self):
        self.update_led_state()
        return self.led_state

    def set_active_led(self, led_number):
        if led_number is None or led_number <= 0:
            if self._send_command("l0"):
                self.led_state = -1
            return

        command = f"l{led_number}"
        if self._send_command(command):
            self.led_state = led_number

    def blink_led(self, led_number, period, blinks):
        if 1 <= led_number <= 9 and period > 0 and blinks > 0:
            command = f"b{led_number}{period}{blinks}"
            self._send_command(command)

    def close(self):
        self._cleanup_serial()
        self._connected = False

    def is_connected(self):
        return self._connected
