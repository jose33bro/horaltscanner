from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class UsbTransport(Protocol):
    def write(self, payload: bytes) -> None:
        ...

    def read_line(self) -> bytes:
        ...


@dataclass
class CrealityUsbDriver:
    transport: UsbTransport

    def ping(self) -> str:
        return self._send("PING")

    def move(self, axis: str, steps: int, speed: int) -> str:
        axis = axis.upper()
        if axis not in {"X", "Y", "Z"}:
            raise ValueError("axis must be X, Y or Z")
        return self._send(f"MOVE {axis} {steps} {speed}")

    def home_y(self) -> str:
        return self._send("HOME Y")

    def read_endstop_y(self) -> bool:
        response = self._send("ENDSTOP Y")
        return response.endswith("1")

    def sync(self, token: str) -> str:
        return self._send(f"SYNC {token}")

    def _send(self, command: str) -> str:
        self.transport.write((command + "\n").encode("ascii"))
        response = self.transport.read_line().decode("ascii", errors="replace").strip()
        if not response.startswith("OK"):
            raise RuntimeError(f"USB command failed: {response}")
        return response
