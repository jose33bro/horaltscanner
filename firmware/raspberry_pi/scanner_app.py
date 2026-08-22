"""
Scanner App - Application principale pour orchestration du scan 3D
Coordonné motion, lasers et capture caméra
"""

import logging
import time
from typing import Optional, Callable, List
from .usb_driver import USBDriver
from .motor_control import MotorController
from .gpio_laser_control import GPIOLaserControl
from . import config

# Configuration logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(config.LOG_FILE),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)


class ScannerApp:
    """Application principale de gestion du scanner 3D Horaltscanner"""

    def __init__(self, usb_port: str = None, use_gpio: bool = True):
        """
        Initialiser l'application scanner
        
        Args:
            usb_port: Port USB (auto-détection si None)
            use_gpio: Utiliser les GPIO physiques (False = simulation)
        """
        self.usb_port = usb_port or config.USB_PORT
        self.use_gpio = use_gpio
        
        # Initialiser les composants
        self.usb = USBDriver(port=self.usb_port, baudrate=config.USB_BAUDRATE)
        self.motors = None
        self.gpio = GPIOLaserControl(use_board=use_gpio)
        
        self.running = False
        self.scan_active = False

    def initialize(self) -> bool:
        """
        Initialiser le scanner complet
        
        Returns:
            True si succès
        """
        logger.info("Initialisation Horaltscanner...")
        
        # Étape 1: Connexion USB
        logger.info("Connexion USB...")
        if not self.usb.connect():
            logger.error("Erreur connexion USB")
            self.gpio.status_error()
            return False
        
        # Étape 2: Créer le contrôleur de moteurs
        self.motors = MotorController(self.usb)
        
        # Étape 3: Homing de tous les axes
        logger.info("Homing tous les axes...")
        self.gpio.led_on("yellow")
        if not self.motors.home_all():
            logger.error("Homing échoué")
            self.gpio.status_error()
            self.usb.disconnect()
            return False
        
        # Étape 4: Initialisation complète
        self.running = True
        self.gpio.status_ready()
        logger.info("Horaltscanner initialisé")
        return True

    def shutdown(self) -> None:
        """Arrêt complet du scanner"""
        logger.info("Arrêt Horaltscanner...")
        self.running = False
        self.scan_active = False
        
        if self.motors:
            # Retourner à la position de départ
            try:
                self.motors.move_abs('Z', 0)
                self.motors.move_abs('Y', 0)
                self.motors.move_abs('X', 0)
            except Exception as e:
                logger.warning(f"Erreur lors du retour position: {e}")
        
        self.gpio.shutdown()
        if self.usb.connected:
            self.usb.disconnect()
        
        logger.info("Arrêt complet")

    # ============================================================
    #   SCAN OPERATIONS
    # ============================================================

    def run_scan(self, num_positions: int = 360, z_heights: List[float] = None,
                 on_capture: Optional[Callable] = None) -> bool:
        """
        Exécuter un scan 3D complet
        
        Args:
            num_positions: Nombre de positions de rotation
            z_heights: Hauteurs Z à scanner (par défaut: config)
            on_capture: Callback appelé à chaque capture (optionnel)
                       reçoit (position, axis_states)
            
        Returns:
            True si succès
        """
        if not self.running:
            logger.error("Scanner non initialisé")
            return False
        
        if not self.motors.is_homed():
            logger.error("Axes non homés")
            return False
        
        if z_heights is None:
            z_heights = config.DEFAULT_SCAN['z_positions']
        
        logger.info(f"Démarrage scan: {num_positions} positions, {len(z_heights)} hauteurs")
        self.scan_active = True
        self.gpio.status_scanning()
        
        try:
            # Calibration initiale
            if not self.motors.move_abs('X', 0) or not self.motors.move_abs('Y', 0):
                logger.error("Erreur positionnement initial")
                return False
            
            # Boucle par hauteur
            for height_idx, z_height in enumerate(z_heights):
                logger.info(f"Scan hauteur {height_idx + 1}/{len(z_heights)}: Z={z_height}mm")
                
                if not self.motors.move_abs('Z', z_height):
                    logger.error(f"Impossible d'atteindre Z={z_height}mm")
                    return False
                
                time.sleep(0.5)  # Stabilisation
                
                # Boucle par position de rotation
                for pos_idx in range(num_positions):
                    # Rotation progressive
                    rotation_angle = (pos_idx / num_positions) * 360  # degrés
                    
                    if not self.motors.move_steps('Y', self._angle_to_steps(rotation_angle)):
                        logger.error(f"Mouvement rotation échoué (pos {pos_idx})")
                        return False
                    
                    time.sleep(config.DEFAULT_SCAN['camera_capture_delay'] / 1000.0)
                    
                    # Trigger capture
                    self.gpio.laser_pulse(config.DEFAULT_SCAN['laser_duration'], side="both")
                    
                    # Synchronisation
                    sync_token = f"H{height_idx}_P{pos_idx}"
                    self.usb.sync(sync_token)
                    
                    # Callback (ex: capturer image)
                    if on_capture:
                        on_capture(pos_idx, self.motors.get_state())
                    
                    if not self.scan_active:
                        logger.info("Scan interrompu par l'utilisateur")
                        return False
            
            logger.info("Scan complété avec succès")
            self.gpio.status_ready()
            return True
            
        except Exception as e:
            logger.error(f"Erreur lors du scan: {e}")
            self.gpio.status_error()
            return False
        
        finally:
            self.scan_active = False

    def cancel_scan(self) -> None:
        """Annuler le scan en cours"""
        logger.info("Annulation scan")
        self.scan_active = False

    def move_to(self, x: float = None, y: float = None, z: float = None) -> bool:
        """
        Déplacer vers une position spécifique
        
        Args:
            x, y, z: Positions en mm (None = pas de changement)
            
        Returns:
            True si succès
        """
        if not self.running or not self.motors:
            logger.error("Scanner non initialisé")
            return False
        
        try:
            if x is not None and not self.motors.move_abs('X', x):
                return False
            if y is not None and not self.motors.move_abs('Y', y):
                return False
            if z is not None and not self.motors.move_abs('Z', z):
                return False
            return True
        except Exception as e:
            logger.error(f"Erreur mouvement: {e}")
            return False

    def laser_test(self, duration_ms: int = 100) -> None:
        """Test des lasers"""
        logger.info(f"Test laser {duration_ms}ms")
        self.gpio.laser_pulse(duration_ms, side="both")

    def led_test(self) -> None:
        """Test LED RGB"""
        logger.info("Test LED RGB")
        for color in ["red", "green", "blue", "yellow", "cyan", "magenta", "white"]:
            self.gpio.led_on(color)
            time.sleep(0.2)
        self.gpio.led_off()

    def fan_test(self, duration_s: int = 2) -> None:
        """Test ventilateur"""
        logger.info(f"Test fan {duration_s}s")
        self.gpio.fan_on(1.0)
        time.sleep(duration_s)
        self.gpio.fan_off()

    # ============================================================
    #   HELPERS PRIVÉS
    # ============================================================

    def _angle_to_steps(self, angle_deg: float) -> int:
        """Convertir angle (degrés) en steps pour axe Y (plateau)"""
        motor_cfg = config.MOTORS['Y']
        full_rotation_steps = (config.STEPS_PER_ROTATION * motor_cfg['microsteps'] * 
                              motor_cfg['rotation_distance'] / motor_cfg['rotation_distance'])
        return int((angle_deg / 360.0) * full_rotation_steps)

    # ============================================================
    #   CONTEXT MANAGER
    # ============================================================

    def __enter__(self):
        if not self.initialize():
            raise RuntimeError("Scanner initialization failed")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.shutdown()


# ============================================================
#   EXAMPLE USAGE
# ============================================================

if __name__ == "__main__":
    # Exemple simple
    try:
        with ScannerApp(use_gpio=False) as scanner:  # mode simulation
            # Test moteurs
            logger.info("Test déplacement...")
            scanner.move_to(x=50, y=0, z=100)
            
            # Test lasers
            scanner.laser_test()
            
            # Test LED
            scanner.led_test()
            
            # Scan simple
            logger.info("Lancement mini-scan...")
            scanner.run_scan(num_positions=10, z_heights=[50, 100])
            
    except Exception as e:
        logger.error(f"Erreur application: {e}")
