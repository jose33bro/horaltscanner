from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import logging
import re
import serial
import struct
from typing import Protocol


CMD_MOVE_X = 0x01
CMD_MOVE_Y = 0x02
CMD_MOVE_Z = 0x03
CMD_HOME_X = 0x10
CMD_HOME_Y = 0x11
CMD_HOME_Z = 0x12
CMD_SET_SPEED = 0x20
CMD_GET_STATUS = 0x30
CMD_STOP = 0x40

STATUS_OK = 0x00

PACKET_FORMAT = "<BBiiB"
RESPONSE_FORMAT = "<BBiiiBB"

logger = logging.getLogger(__name__)


class USBProtocolError(RuntimeError):
    """Raised on malformed USB protocol responses."""


class USBTransport(Protocol):
    def exchange(self, payload: bytes) -> bytes:
        """Send one command and return one response frame."""


@dataclass(frozen=True)
class ScannerStatus:
    status: int
    error: int
    pos_x: int
    pos_y: int
    pos_z: int
    endstop_mask: int


class PyUSBTransport:
    """USB transport for a custom STM32 scanner firmware endpoint pair."""

    def __init__(self, vendor_id: int, product_id: int, out_ep: int = 0x01, in_ep: int = 0x81, timeout_ms: int = 250):
        try:
            import usb.core
            import usb.util
        except ImportError as exc:  # pragma: no cover - depends on runtime environment
            raise RuntimeError("pyusb is required for PyUSBTransport") from exc

        self._usb_core = usb.core
        self._device = usb.core.find(idVendor=vendor_id, idProduct=product_id)
        if self._device is None:
            raise RuntimeError("Scanner USB device not found")

        self._out_ep = out_ep
        self._in_ep = in_ep
        self._timeout_ms = timeout_ms

    def exchange(self, payload: bytes) -> bytes:
        self._device.write(self._out_ep, payload, timeout=self._timeout_ms)
        return bytes(self._device.read(self._in_ep, struct.calcsize(RESPONSE_FORMAT), timeout=self._timeout_ms))


class USBScannerDriver:
    def __init__(self, transport: USBTransport):
        self._transport = transport

    @staticmethod
    def checksum(payload: bytes) -> int:
        value = 0
        for byte in payload:
            value ^= byte
        return value

    def _build_packet(self, command: int, axis: int = 0, value: int = 0, speed: int = 0) -> bytes:
        head = struct.pack("<BBii", command, axis, value, speed)
        return struct.pack(PACKET_FORMAT, command, axis, value, speed, self.checksum(head))

    def _parse_response(self, response: bytes) -> ScannerStatus:
        if len(response) != struct.calcsize(RESPONSE_FORMAT):
            raise USBProtocolError(f"Bad response size: {len(response)}")

        status, error, pos_x, pos_y, pos_z, endstop_mask, checksum = struct.unpack(RESPONSE_FORMAT, response)
        expected = self.checksum(response[:-1])
        if checksum != expected:
            raise USBProtocolError("Bad response checksum")

        return ScannerStatus(status=status, error=error, pos_x=pos_x, pos_y=pos_y, pos_z=pos_z, endstop_mask=endstop_mask)

    def _exchange(self, command: int, axis: int = 0, value: int = 0, speed: int = 0) -> ScannerStatus:
        packet = self._build_packet(command, axis=axis, value=value, speed=speed)
        response = self._transport.exchange(packet)
        parsed = self._parse_response(response)
        if parsed.status != STATUS_OK:
            raise USBProtocolError(f"Firmware error code: {parsed.error}")
        return parsed

    def move_x(self, steps: int, speed: int = 0) -> ScannerStatus:
        return self._exchange(CMD_MOVE_X, value=steps, speed=speed)

    def move_y(self, steps: int, speed: int = 0) -> ScannerStatus:
        return self._exchange(CMD_MOVE_Y, value=steps, speed=speed)

    def move_z(self, steps: int, speed: int = 0) -> ScannerStatus:
        return self._exchange(CMD_MOVE_Z, value=steps, speed=speed)

    def home_x(self) -> ScannerStatus:
        return self._exchange(CMD_HOME_X)

    def home_y(self) -> ScannerStatus:
        return self._exchange(CMD_HOME_Y)

    def home_z(self) -> ScannerStatus:
        return self._exchange(CMD_HOME_Z)

    def home_axis(self, axis: str) -> ScannerStatus:
        axis_normalized = axis.upper()
        if axis_normalized == "X":
            return self.home_x()
        if axis_normalized == "Y":
            return self.home_y()
        if axis_normalized == "Z":
            return self.home_z()
        raise ValueError(f"Unsupported axis: {axis}")

    def set_speed(self, axis: str, speed: int) -> ScannerStatus:
        axis_map = {"X": 0, "Y": 1, "Z": 2}
        axis_normalized = axis.upper()
        if axis_normalized not in axis_map:
            raise ValueError(f"Unsupported axis: {axis}")
        return self._exchange(CMD_SET_SPEED, axis=axis_map[axis_normalized], speed=speed)

    def get_status(self) -> ScannerStatus:
        return self._exchange(CMD_GET_STATUS)

    def stop(self) -> ScannerStatus:
        return self._exchange(CMD_STOP)


# ---------------------------------------------------------------------------
# USBDriver - text-protocol (serial) driver used by MotorController
# ---------------------------------------------------------------------------

class USBDriver:
    """Serial text-protocol driver for the Creality V4.2.2 firmware.

    Commands are sent as ASCII text lines; responses are expected to
    start with 'OK' for success or 'ERR' for failure.

    Axis codes: X=0 (translation), Y=1 (rotation), Z=2 (height)
    """

    # USB serial path for Creality V4.2.2
    DEFAULT_PORT = "/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0"
    BAUDRATE = 115200

    def __init__(self, port: str | None = None, baudrate: int = BAUDRATE, timeout: float = 5.0):
        self.port = port or self.DEFAULT_PORT
        self.baudrate = baudrate
        self.timeout = timeout
        self.connected = False
        self.ser = None  # serial.Serial instance (set on connect)

    def connect(self) -> bool:
        """Open the serial connection.  Returns True on success."""
        try:
            self.ser = serial.Serial(
                self.port, baudrate=self.baudrate, timeout=self.timeout
            )
            self.connected = True
            logger.info("USBDriver connected on %s", self.port)
            return True
        except Exception as exc:
            logger.warning("USBDriver connect failed: %s", exc)
            self.connected = False
            return False

    def disconnect(self) -> None:
        if self.ser is not None:
            try:
                self.ser.close()
            except Exception:
                pass
            self.ser = None
        self.connected = False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _send(self, command: str) -> bool:
        """Send a command and check for 'OK' response.  Returns True on success."""
        if self.ser is None:
            logger.warning("USBDriver: not connected, cannot send '%s'", command)
            return False
        try:
            self.ser.write((command + "\n").encode("ascii"))
            response = self.ser.readline().decode("ascii", errors="replace").strip()
            if response.startswith("OK"):
                return True
            logger.warning("USBDriver rejected command '%s': %s", command, response)
            return False
        except Exception as exc:
            logger.error("USBDriver serial error: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Motor commands
    # ------------------------------------------------------------------

    def move(self, axis: str, steps: int, speed: int = 0) -> bool:
        """Move *axis* by *steps* steps at *speed* steps/s."""
        axis = axis.upper()
        return self._send(f"MOVE_{axis} {steps} {speed}")

    def home(self, axis: str) -> bool:
        """Home *axis* (move to endstop / reference point)."""
        axis = axis.upper()
        return self._send(f"HOME_{axis}")

    def stop(self) -> bool:
        """Emergency stop all motors."""
        return self._send("STOP")

    # ------------------------------------------------------------------
    # Y-axis endstop (rotation counter)
    # ------------------------------------------------------------------

    def read_endstop_y(self) -> bool:
        """Return True when the Y endstop (full-rotation detector) is triggered."""
        if self.ser is None:
            return False
        try:
            self.ser.write(b"ENDSTOP_Y\n")
            response = self.ser.readline().decode("ascii", errors="replace").strip()
            return response.endswith("1")
        except Exception as exc:
            logger.error("USBDriver endstop read error: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Temperature / fan
    # ------------------------------------------------------------------

    def get_temperature(self) -> float | None:
        """Read board temperature (NTC on PA0).  Returns °C or None."""
        if self.ser is None:
            return None
        try:
            self.ser.write(b"GET_TEMP\n")
            response = self.ser.readline().decode("ascii", errors="replace").strip()
            for token in response.split():
                try:
                    return float(token)
                except ValueError:
                    continue
            return None
        except Exception as exc:
            logger.error("USBDriver temperature read error: %s", exc)
            return None

    def fan_control(self, state: str) -> bool:
        """Control the Creality fan: state = 'ON' or 'OFF'."""
        return self._send(f"FAN_{state.upper()}")
