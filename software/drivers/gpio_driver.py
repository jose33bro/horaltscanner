"""Raspberry Pi GPIO Driver
Controls lasers, LED RGB, and fan via GPIO pins
"""

import logging
from typing import Dict, Any, Optional
from gpiozero import OutputDevice, PWMLED
import threading

logger = logging.getLogger(__name__)


class GPIODriver:
    """Controls GPIO outputs on Raspberry Pi"""

    # GPIO pin configuration from printer.cfg
    GPIO_CONFIG = {
        "laser_left": 27,
        "laser_right": 22,
        "led_red": 18,
        "led_green": 13,
        "led_blue": 19,
        "pi_fan": 23,
    }

    def __init__(self):
        """Initialize GPIO driver"""
        self.devices: Dict[str, OutputDevice] = {}
        self.led_state = {"r": 0, "g": 0, "b": 0}
        self.laser_state = {"left": False, "right": False}
        self.fan_speed = 0.0
        self.connected = False
        self._lock = threading.Lock()

    def connect(self) -> bool:
        """Initialize all GPIO pins
        
        Returns:
            True if all pins initialized successfully
        """
        try:
            # Initialize laser pins (simple digital output)
            self.devices["laser_left"] = OutputDevice(
                self.GPIO_CONFIG["laser_left"]
            )
            self.devices["laser_left"].off()
            
            self.devices["laser_right"] = OutputDevice(
                self.GPIO_CONFIG["laser_right"]
            )
            self.devices["laser_right"].off()

            # Initialize LED RGB pins (PWM capable)
            self.devices["led_red"] = PWMLED(self.GPIO_CONFIG["led_red"])
            self.devices["led_red"].off()
            
            self.devices["led_green"] = PWMLED(self.GPIO_CONFIG["led_green"])
            self.devices["led_green"].off()
            
            self.devices["led_blue"] = PWMLED(self.GPIO_CONFIG["led_blue"])
            self.devices["led_blue"].off()

            # Initialize fan pin (PWM capable)
            self.devices["pi_fan"] = PWMLED(self.GPIO_CONFIG["pi_fan"])
            self.devices["pi_fan"].off()

            self.connected = True
            logger.info("✓ GPIO driver initialized successfully")
            return True

        except Exception as e:
            logger.error(f"✗ Failed to initialize GPIO: {e}")
            self.connected = False
            return False

    def disconnect(self):
        """Cleanup GPIO pins"""
        try:
            for device in self.devices.values():
                device.close()
            self.devices.clear()
            self.connected = False
            logger.info("GPIO driver disconnected")
        except Exception as e:
            logger.error(f"Error during GPIO cleanup: {e}")

    # ========== LASER CONTROL ==========

    def laser_on(self, side: str) -> bool:
        """Turn laser on
        
        Args:
            side: "left" or "right"
            
        Returns:
            True if successful
        """
        if side not in ["left", "right"]:
            logger.error(f"Invalid laser side: {side}")
            return False

        if not self.connected:
            logger.error("GPIO driver not connected")
            return False

        try:
            with self._lock:
                pin_name = f"laser_{side}"
                if pin_name in self.devices:
                    self.devices[pin_name].on()
                    self.laser_state[side] = True
                    logger.info(f"Laser {side}: ON")
                    return True
        except Exception as e:
            logger.error(f"Failed to turn on laser {side}: {e}")

        return False

    def laser_off(self, side: str) -> bool:
        """Turn laser off
        
        Args:
            side: "left" or "right"
            
        Returns:
            True if successful
        """
        if side not in ["left", "right"]:
            logger.error(f"Invalid laser side: {side}")
            return False

        if not self.connected:
            logger.error("GPIO driver not connected")
            return False

        try:
            with self._lock:
                pin_name = f"laser_{side}"
                if pin_name in self.devices:
                    self.devices[pin_name].off()
                    self.laser_state[side] = False
                    logger.info(f"Laser {side}: OFF")
                    return True
        except Exception as e:
            logger.error(f"Failed to turn off laser {side}: {e}")

        return False

    def get_laser_status(self) -> Dict[str, Any]:
        """Get laser status
        
        Returns:
            Dictionary with laser states
        """
        return {"left": self.laser_state["left"], "right": self.laser_state["right"]}

    # ========== LED RGB CONTROL ==========

    def led_set(self, r: int, g: int, b: int) -> bool:
        """Set LED RGB color
        
        Args:
            r: Red value (0-255)
            g: Green value (0-255)
            b: Blue value (0-255)
            
        Returns:
            True if successful
        """
        if not self.connected:
            logger.error("GPIO driver not connected")
            return False

        # Clamp values
        r = max(0, min(255, r))
        g = max(0, min(255, g))
        b = max(0, min(255, b))

        try:
            with self._lock:
                # Convert 0-255 to 0.0-1.0 for gpiozero PWM
                r_val = r / 255.0
                g_val = g / 255.0
                b_val = b / 255.0

                if "led_red" in self.devices:
                    self.devices["led_red"].value = r_val
                if "led_green" in self.devices:
                    self.devices["led_green"].value = g_val
                if "led_blue" in self.devices:
                    self.devices["led_blue"].value = b_val

                self.led_state = {"r": r, "g": g, "b": b}
                logger.info(f"LED RGB: R={r} G={g} B={b}")
                return True

        except Exception as e:
            logger.error(f"Failed to set LED color: {e}")

        return False

    def led_off(self) -> bool:
        """Turn off all LED
        
        Returns:
            True if successful
        """
        return self.led_set(0, 0, 0)

    def get_led_status(self) -> Dict[str, Any]:
        """Get LED status
        
        Returns:
            Dictionary with LED state (r, g, b)
        """
        return self.led_state.copy()

    # ========== FAN CONTROL ==========

    def set_fan_speed(self, speed: float) -> bool:
        """Set Pi fan speed (0.0-1.0)
        
        Args:
            speed: Speed 0.0-1.0
            
        Returns:
            True if successful
        """
        if not self.connected:
            logger.error("GPIO driver not connected")
            return False

        # Clamp value
        speed = max(0.0, min(1.0, speed))

        try:
            with self._lock:
                if "pi_fan" in self.devices:
                    self.devices["pi_fan"].value = speed
                    self.fan_speed = speed
                    logger.info(f"Pi fan: {speed*100:.0f}%")
                    return True
        except Exception as e:
            logger.error(f"Failed to set fan speed: {e}")

        return False

    def get_fan_status(self) -> Dict[str, Any]:
        """Get fan status
        
        Returns:
            Dictionary with fan speed (0-1.0)
        """
        return {"speed": self.fan_speed}
