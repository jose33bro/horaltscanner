"""STM32F103 Motor Controller Driver
Communicates with Creality 4.2.2 mainboard via serial port
"""

import logging
import serial
import threading
import time
from typing import Optional, Dict, Any
from queue import Queue, Empty

logger = logging.getLogger(__name__)


class STM32Driver:
    """Controls motors, fans, and temperature sensors on STM32F103RET6"""

    # Motor configuration from printer.cfg
    MOTOR_CONFIG = {
        "x": {
            "step_pin": "PC2",
            "dir_pin": "PB9",
            "enable_pin": "PC3",
            "rotation_distance": 40,
            "microsteps": 16,
            "max_position": 210,
        },
        "y": {
            "step_pin": "PB8",
            "dir_pin": "PB7",
            "enable_pin": "PC3",
            "rotation_distance": 620,
            "microsteps": 16,
            "max_position": 628.32,
        },
        "z": {
            "step_pin": "PB6",
            "dir_pin": "PB5",
            "enable_pin": "PC3",
            "rotation_distance": 8,
            "microsteps": 16,
            "max_position": 270,
        },
    }

    def __init__(
        self,
        port: str = "/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0",
        baudrate: int = 115200,
    ):
        """Initialize STM32 driver
        
        Args:
            port: Serial port path
            baudrate: Serial communication speed
        """
        self.port = port
        self.baudrate = baudrate
        self.serial_conn: Optional[serial.Serial] = None
        self.connected = False

        # Motor state
        self.motor_positions = {"x": 0.0, "y": 0.0, "z": 0.0}
        self.motor_moving = {"x": False, "y": False, "z": False}
        self.temperature = 0.0
        self.fan_speeds = {"creality": 0.0, "temperature": 0.0}

        # Communication queue
        self.cmd_queue: Queue = Queue()
        self.response_queue: Queue = Queue()

        # Thread control
        self.running = False
        self.reader_thread: Optional[threading.Thread] = None

    def connect(self) -> bool:
        """Connect to STM32 via serial port
        
        Returns:
            True if connection successful
        """
        try:
            self.serial_conn = serial.Serial(
                self.port, self.baudrate, timeout=1.0
            )
            time.sleep(0.5)  # Wait for board to stabilize
            self.connected = True
            self.running = True

            # Start reader thread
            self.reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
            self.reader_thread.start()

            logger.info(f"✓ STM32 connected on {self.port}")
            return True

        except Exception as e:
            logger.error(f"✗ Failed to connect STM32: {e}")
            self.connected = False
            return False

    def disconnect(self):
        """Disconnect from STM32"""
        self.running = False
        if self.reader_thread:
            self.reader_thread.join(timeout=2.0)
        if self.serial_conn:
            self.serial_conn.close()
        self.connected = False
        logger.info("STM32 disconnected")

    def _reader_loop(self):
        """Background thread: read responses from STM32"""
        buffer = ""
        while self.running:
            try:
                if self.serial_conn and self.serial_conn.in_waiting:
                    data = self.serial_conn.read(self.serial_conn.in_waiting).decode(
                        "utf-8", errors="ignore"
                    )
                    buffer += data

                    # Process complete lines
                    while "\n" in buffer:
                        line, buffer = buffer.split("\n", 1)
                        line = line.strip()
                        if line:
                            self.response_queue.put(line)

            except Exception as e:
                logger.warning(f"Serial read error: {e}")
                time.sleep(0.1)

    def _send_command(self, cmd: str) -> bool:
        """Send command to STM32
        
        Args:
            cmd: Command string
            
        Returns:
            True if sent successfully
        """
        if not self.connected or not self.serial_conn:
            logger.error("STM32 not connected")
            return False

        try:
            self.serial_conn.write((cmd + "\n").encode())
            self.serial_conn.flush()
            return True
        except Exception as e:
            logger.error(f"Failed to send command: {e}")
            return False

    def _read_response(self, timeout: float = 2.0) -> Optional[str]:
        """Read response from STM32
        
        Args:
            timeout: Wait time for response
            
        Returns:
            Response string or None
        """
        try:
            return self.response_queue.get(timeout=timeout)
        except Empty:
            return None

    # ========== MOTOR CONTROL ==========

    def move_motor(self, axis: str, distance: float) -> bool:
        """Move motor on specified axis
        
        Args:
            axis: "x", "y", or "z"
            distance: Distance in mm
            
        Returns:
            True if command sent successfully
        """
        if axis not in ["x", "y", "z"]:
            logger.error(f"Invalid axis: {axis}")
            return False

        # Check bounds
        max_pos = self.MOTOR_CONFIG[axis]["max_position"]
        new_pos = self.motor_positions[axis] + distance

        if new_pos < 0 or new_pos > max_pos:
            logger.error(
                f"Motor {axis} out of bounds: {new_pos} (0-{max_pos})"
            )
            return False

        cmd = f"MOTOR_{axis.upper()}_MOVE {distance}"
        if self._send_command(cmd):
            self.motor_moving[axis] = True
            self.motor_positions[axis] = new_pos
            logger.info(f"Move {axis}: {distance}mm → pos={new_pos:.2f}mm")
            return True

        return False

    def home_motor(self, axis: str = "all") -> bool:
        """Home motor(s)
        
        Args:
            axis: "x", "y", "z", or "all"
            
        Returns:
            True if command sent successfully
        """
        if axis == "all":
            axes = ["x", "y", "z"]
        elif axis in ["x", "y", "z"]:
            axes = [axis]
        else:
            logger.error(f"Invalid axis: {axis}")
            return False

        success = True
        for ax in axes:
            cmd = f"MOTOR_{ax.upper()}_HOME"
            if self._send_command(cmd):
                self.motor_positions[ax] = 0.0
                self.motor_moving[ax] = False
                logger.info(f"Home {ax}")
            else:
                success = False

        return success

    def stop_motor(self, axis: str = "all") -> bool:
        """Stop motor(s)
        
        Args:
            axis: "x", "y", "z", or "all"
            
        Returns:
            True if command sent successfully
        """
        if axis == "all":
            axes = ["x", "y", "z"]
        elif axis in ["x", "y", "z"]:
            axes = [axis]
        else:
            logger.error(f"Invalid axis: {axis}")
            return False

        success = True
        for ax in axes:
            cmd = f"MOTOR_{ax.upper()}_STOP"
            if self._send_command(cmd):
                self.motor_moving[ax] = False
                logger.info(f"Stop {ax}")
            else:
                success = False

        return success

    def get_motor_status(self) -> Dict[str, Any]:
        """Get motor status
        
        Returns:
            Status dictionary with positions and movement state
        """
        return {
            "positions": self.motor_positions.copy(),
            "moving": self.motor_moving.copy(),
            "temperature_c": self.temperature,
        }

    # ========== FAN CONTROL ==========

    def set_fan_speed(self, fan: str, speed: float) -> bool:
        """Set fan speed (0-1.0)
        
        Args:
            fan: "creality"/"board" (PA0) or "temperature" (PA8)
            speed: Speed 0.0-1.0
            
        Returns:
            True if command sent successfully
        """
        fan_aliases = {"board": "creality", "creality": "creality", "temperature": "temperature"}
        normalized_fan = fan_aliases.get(fan)
        if normalized_fan is None:
            logger.error(f"Invalid fan: {fan}")
            return False

        speed = max(0.0, min(1.0, speed))

        # Convert to 0-255
        pwm_value = int(speed * 255)
        if normalized_fan == "creality":
            cmd = f"FAN_PA0_PWM {pwm_value}"
        else:
            cmd = f"FAN_PA8_PWM {pwm_value}"

        if self._send_command(cmd):
            self.fan_speeds[normalized_fan] = speed
            logger.info(f"Set {normalized_fan} fan: {speed*100:.0f}%")
            return True

        return False

    def get_fan_status(self) -> Dict[str, float]:
        """Get tracked fan speeds for STM32-controlled fans."""
        return self.fan_speeds.copy()

    # ========== TEMPERATURE ==========

    def read_board_temperature(self) -> Optional[float]:
        """Read board temperature
        
        Returns:
            Temperature in Celsius or None
        """
        if not self._send_command("TEMP_READ"):
            return None

        response = self._read_response()
        if response:
            try:
                self.temperature = float(response.split()[-1])
                return self.temperature
            except (ValueError, IndexError):
                logger.warning(f"Invalid temperature response: {response}")

        return None

    def read_temperature(self) -> Optional[float]:
        """Backward-compatible alias for board temperature reading."""
        return self.read_board_temperature()
