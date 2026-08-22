"""
GPIO Laser Control - Gestion des lasers, LED RGB et ventilateurs
Utilise gpiozero pour une abstraction portable
"""

import logging
import time
from typing import Tuple

try:
    from gpiozero import LED, PWMOutputDevice, Device
    from gpiozero.pins.rpigpio import RPiGPIOFactory
    GPIO_AVAILABLE = True
except ImportError:
    GPIO_AVAILABLE = False
    logging.warning("gpiozero non disponible - GPIO en mode simulation")

from . import config

logger = logging.getLogger(__name__)


class GPIOLaserControl:
    """Gestion des sorties GPIO: lasers, LED RGB, ventilateurs"""

    def __init__(self, use_board: bool = True):
        """
        Initialiser les GPIO
        
        Args:
            use_board: Si True, utilise GPIO réel; False pour simulation
        """
        self.use_board = use_board and GPIO_AVAILABLE
        
        if not GPIO_AVAILABLE:
            logger.warning("gpiozero non disponible - mode simulation")
            self.laser_gauche = None
            self.laser_droit = None
            self.led_r = None
            self.led_g = None
            self.led_b = None
            self.fan_pi = None
            return

        try:
            if not self.use_board:
                Device.pin_factory = None  # Mode simulation
                
            # Lasers (digital output)
            self.laser_gauche = LED(config.GPIO_LASER_GAUCHE)
            self.laser_droit = LED(config.GPIO_LASER_DROIT)
            
            # LED RGB (PWM)
            self.led_r = PWMOutputDevice(config.GPIO_RGB_R)
            self.led_g = PWMOutputDevice(config.GPIO_RGB_G)
            self.led_b = PWMOutputDevice(config.GPIO_RGB_B)
            
            # Ventilateur Pi
            self.fan_pi = PWMOutputDevice(config.GPIO_FAN_PI)
            
            # État initial
            self.lasers_off()
            self.led_off()
            self.fan_off()
            
            logger.info("GPIO initialisé avec succès")
            
        except Exception as e:
            logger.error(f"Erreur initialisation GPIO: {e}")
            self.use_board = False

    # ============================================================
    #   LASERS
    # ============================================================

    def laser_on(self, side: str = "both") -> None:
        """
        Allumer le(s) laser(s)
        
        Args:
            side: "gauche", "droit" ou "both"
        """
        if not self.laser_gauche or not self.laser_droit:
            logger.debug(f"[SIM] Laser ON: {side}")
            return

        if side in ["gauche", "both"]:
            self.laser_gauche.on()
        if side in ["droit", "both"]:
            self.laser_droit.on()
            
        logger.debug(f"Laser ON: {side}")

    def laser_off(self, side: str = "both") -> None:
        """
        Éteindre le(s) laser(s)
        
        Args:
            side: "gauche", "droit" ou "both"
        """
        if not self.laser_gauche or not self.laser_droit:
            logger.debug(f"[SIM] Laser OFF: {side}")
            return

        if side in ["gauche", "both"]:
            self.laser_gauche.off()
        if side in ["droit", "both"]:
            self.laser_droit.off()
            
        logger.debug(f"Laser OFF: {side}")

    def laser_pulse(self, duration_ms: int = 100, side: str = "both") -> None:
        """
        Pulse laser pour une durée donnée
        
        Args:
            duration_ms: Durée en millisecondes
            side: "gauche", "droit" ou "both"
        """
        self.laser_on(side)
        time.sleep(duration_ms / 1000.0)
        self.laser_off(side)
        logger.debug(f"Laser pulse: {duration_ms}ms ({side})")

    # ============================================================
    #   LED RGB
    # ============================================================

    def led_set_color(self, r: float = 0.0, g: float = 0.0, b: float = 0.0) -> None:
        """
        Définir la couleur LED RGB
        
        Args:
            r, g, b: Valeurs 0.0-1.0
        """
        if not self.led_r or not self.led_g or not self.led_b:
            logger.debug(f"[SIM] LED RGB: ({r:.2f}, {g:.2f}, {b:.2f})")
            return

        self.led_r.value = max(0.0, min(1.0, r))
        self.led_g.value = max(0.0, min(1.0, g))
        self.led_b.value = max(0.0, min(1.0, b))
        logger.debug(f"LED RGB: ({r:.2f}, {g:.2f}, {b:.2f})")

    def led_off(self) -> None:
        """Éteindre la LED"""
        self.led_set_color(0.0, 0.0, 0.0)

    def led_on(self, color: str = "white") -> None:
        """
        Allumer la LED avec une couleur
        
        Args:
            color: "red", "green", "blue", "yellow", "cyan", "magenta", "white"
        """
        colors = {
            "red": (1.0, 0.0, 0.0),
            "green": (0.0, 1.0, 0.0),
            "blue": (0.0, 0.0, 1.0),
            "yellow": (1.0, 1.0, 0.0),
            "cyan": (0.0, 1.0, 1.0),
            "magenta": (1.0, 0.0, 1.0),
            "white": (1.0, 1.0, 1.0),
        }
        
        if color not in colors:
            logger.warning(f"Couleur inconnue: {color}")
            return
            
        r, g, b = colors[color]
        self.led_set_color(r, g, b)

    def led_pulse(self, color: str = "blue", duration_ms: int = 500) -> None:
        """
        Pulse LED avec une couleur
        
        Args:
            color: Couleur LED
            duration_ms: Durée en ms
        """
        self.led_on(color)
        time.sleep(duration_ms / 1000.0)
        self.led_off()

    # ============================================================
    #   VENTILATEUR
    # ============================================================

    def fan_on(self, speed: float = 1.0) -> None:
        """
        Allumer le ventilateur Pi
        
        Args:
            speed: Vitesse 0.0-1.0
        """
        if not self.fan_pi:
            logger.debug(f"[SIM] Fan ON: {speed:.2f}")
            return

        self.fan_pi.value = max(0.0, min(1.0, speed))
        logger.debug(f"Fan ON: {speed:.2f}")

    def fan_off(self) -> None:
        """Éteindre le ventilateur"""
        if not self.fan_pi:
            logger.debug("[SIM] Fan OFF")
            return
        self.fan_pi.value = 0.0
        logger.debug("Fan OFF")

    def fan_set_speed(self, speed: float) -> None:
        """
        Définir la vitesse du ventilateur
        
        Args:
            speed: Vitesse 0.0-1.0
        """
        self.fan_on(speed)

    # ============================================================
    #   PRESETS
    # ============================================================

    def status_idle(self) -> None:
        """LED vert = système inactif"""
        self.laser_off()
        self.led_on("green")

    def status_ready(self) -> None:
        """LED bleu = système prêt"""
        self.laser_off()
        self.led_on("blue")

    def status_scanning(self) -> None:
        """LED rouge = scan en cours"""
        self.led_on("red")

    def status_error(self) -> None:
        """LED rouge pulse = erreur"""
        self.led_pulse("red", 200)

    def shutdown(self) -> None:
        """Arrêt complet"""
        logger.info("Shutdown GPIO...")
        self.laser_off()
        self.led_off()
        self.fan_off()

    # ============================================================
    #   CONTEXT MANAGER
    # ============================================================

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.shutdown()
