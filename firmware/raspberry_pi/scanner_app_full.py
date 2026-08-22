"""
Scanner App Extended - Intégration caméras et LiDAR
Version complète avec acquisition capteurs
"""

import logging
import time
from pathlib import Path
from typing import Optional, Callable, List, Tuple
from datetime import datetime

from .usb_driver import USBDriver
from .motor_control import MotorController
from .gpio_laser_control import GPIOLaserControl
from .camera_acquisition import DualCameraSystem, CameraType
from .lidar_acquisition import TFLunaLiDAR, LiDARFrameBuffer
from . import config

logger = logging.getLogger(__name__)


class ScannerAppFull:
    """Application scanner complète avec capteurs"""

    def __init__(self, usb_port: str = None, lidar_port: str = "/dev/ttyUSB1",
                 output_dir: str = None, use_gpio: bool = True):
        """
        Initialiser l'application scanner complète
        
        Args:
            usb_port: Port USB moteurs
            lidar_port: Port USB LiDAR
            output_dir: Répertoire de sortie des scans
            use_gpio: Utiliser GPIO physiques
        """
        self.usb_port = usb_port or config.USB_PORT
        self.lidar_port = lidar_port
        self.output_dir = Path(output_dir or f"/tmp/horaltscanner_scan_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Initialiser composants
        self.usb = USBDriver(port=self.usb_port, baudrate=config.USB_BAUDRATE)
        self.motors = None
        self.gpio = GPIOLaserControl(use_board=use_gpio)
        self.cameras = None
        self.lidar = None
        self.lidar_buffer = LiDARFrameBuffer(max_size=10000)
        
        self.running = False
        self.scan_active = False

    def initialize(self) -> bool:
        """
        Initialiser le scanner complet avec tous les capteurs
        
        Returns:
            True si succès
        """
        logger.info("Initialisation Horaltscanner complète...")
        
        # Étape 1: USB
        logger.info("Connexion USB moteurs...")
        if not self.usb.connect():
            logger.error("Erreur connexion USB")
            self.gpio.status_error()
            return False
        
        # Étape 2: Moteurs
        self.motors = MotorController(self.usb)
        logger.info("Homing tous les axes...")
        self.gpio.led_on("yellow")
        if not self.motors.home_all():
            logger.error("Homing échoué")
            self.gpio.status_error()
            self.usb.disconnect()
            return False
        
        # Étape 3: Caméras
        logger.info("Initialisation caméras...")
        try:
            self.cameras = DualCameraSystem(
                output_dir=self.output_dir / "images",
                capture_mode="synchronized"
            )
            if not self.cameras.initialized:
                logger.warning("Caméras non disponibles - scan sans images")
                self.cameras = None
        except Exception as e:
            logger.warning(f"Erreur initialisation caméras: {e}")
            self.cameras = None
        
        # Étape 4: LiDAR
        logger.info("Initialisation LiDAR TF-Luna...")
        self.lidar = TFLunaLiDAR(port=self.lidar_port)
        if not self.lidar.connect():
            logger.warning("LiDAR non disponible - scan sans mesures de distance")
            self.lidar = None
        
        # Étape 5: Prêt
        self.running = True
        self.gpio.status_ready()
        logger.info("Horaltscanner complètement initialisé")
        return True

    def run_full_scan(self, num_positions: int = 360, z_heights: List[float] = None,
                      lidar_samples: int = 20) -> bool:
        """
        Exécuter un scan 3D complet avec capteurs
        
        Args:
            num_positions: Positions de rotation
            z_heights: Hauteurs Z à scanner
            lidar_samples: Nombre de mesures LiDAR par position
            
        Returns:
            True si succès
        """
        if not self.running:
            logger.error("Scanner non initialisé")
            return False
        
        if z_heights is None:
            z_heights = config.DEFAULT_SCAN['z_positions']
        
        logger.info(f"Démarrage scan complet: {num_positions} positions, {len(z_heights)} hauteurs")
        self.scan_active = True
        self.gpio.status_scanning()
        
        scan_metadata = {
            'start_time': datetime.now().isoformat(),
            'num_positions': num_positions,
            'z_heights': z_heights,
            'total_frames': 0,
            'lidar_measurements': 0,
        }
        
        try:
            for height_idx, z_height in enumerate(z_heights):
                logger.info(f"Hauteur {height_idx + 1}/{len(z_heights)}: Z={z_height}mm")
                
                if not self.motors.move_abs('Z', z_height):
                    logger.error(f"Impossible atteindre Z={z_height}mm")
                    return False
                
                time.sleep(0.5)  # Stabilisation
                
                for pos_idx in range(num_positions):
                    # Rotation
                    rotation_angle = (pos_idx / num_positions) * 360
                    if not self.motors.move_steps('Y', self._angle_to_steps(rotation_angle)):
                        logger.error(f"Mouvement rotation échoué")
                        return False
                    
                    time.sleep(config.DEFAULT_SCAN['camera_capture_delay'] / 1000.0)
                    
                    # --- CAPTURER ---
                    
                    # Trigger lasers + capture images
                    self.gpio.laser_pulse(config.DEFAULT_SCAN['laser_duration'], side="both")
                    
                    img_paths = None
                    if self.cameras:
                        pos_name = f"h{height_idx:02d}_p{pos_idx:04d}"
                        img_paths = self.cameras.capture_pair(pos_name)
                        if img_paths[0] or img_paths[1]:
                            scan_metadata['total_frames'] += 1
                    
                    # Mesurer distance LiDAR
                    lidar_data = []
                    if self.lidar:
                        for _ in range(lidar_samples):
                            meas = self.lidar.read_measurement()
                            if meas:
                                lidar_data.append(meas)
                                self.lidar_buffer.add(meas)
                                scan_metadata['lidar_measurements'] += 1
                            time.sleep(0.01)  # 10ms entre mesures
                    
                    # Sync
                    sync_token = f"H{height_idx}_P{pos_idx}"
                    self.usb.sync(sync_token)
                    
                    logger.debug(f"Position {pos_idx}/{num_positions} - Images: {img_paths}, LiDAR: {len(lidar_data)} mesures")
                    
                    if not self.scan_active:
                        logger.info("Scan interrompu")
                        return False
            
            # Sauvegarder les données LiDAR
            if self.lidar and self.lidar_buffer.size() > 0:
                lidar_file = self.output_dir / "lidar_measurements.csv"
                self.lidar.save_measurements(self.lidar_buffer.get_all(), lidar_file)
            
            # Sauvegarder métadonnées
            scan_metadata['end_time'] = datetime.now().isoformat()
            self._save_metadata(scan_metadata)
            
            logger.info(f"Scan complété: {scan_metadata['total_frames']} images, "
                       f"{scan_metadata['lidar_measurements']} mesures LiDAR")
            self.gpio.status_ready()
            return True
            
        except Exception as e:
            logger.error(f"Erreur scan: {e}")
            self.gpio.status_error()
            return False
        
        finally:
            self.scan_active = False

    def shutdown(self) -> None:
        """Arrêt complet"""
        logger.info("Arrêt Horaltscanner...")
        self.running = False
        self.scan_active = False
        
        if self.motors:
            try:
                self.motors.move_abs('Z', 0)
                self.motors.move_abs('Y', 0)
                self.motors.move_abs('X', 0)
            except Exception as e:
                logger.warning(f"Erreur retour position: {e}")
        
        if self.cameras:
            self.cameras.disconnect()
        if self.lidar:
            self.lidar.disconnect()
        
        self.gpio.shutdown()
        if self.usb.connected:
            self.usb.disconnect()
        
        logger.info("Arrêt complet")

    def _angle_to_steps(self, angle_deg: float) -> int:
        """Convertir angle en steps"""
        motor_cfg = config.MOTORS['Y']
        full_rotation_steps = (config.STEPS_PER_ROTATION * motor_cfg['microsteps'] * 
                              motor_cfg['rotation_distance'] / motor_cfg['rotation_distance'])
        return int((angle_deg / 360.0) * full_rotation_steps)

    def _save_metadata(self, metadata: dict) -> None:
        """Sauvegarder les métadonnées du scan"""
        import json
        try:
            metadata_file = self.output_dir / "scan_metadata.json"
            with open(metadata_file, 'w') as f:
                json.dump(metadata, f, indent=2)
            logger.info(f"Métadonnées sauvegardées: {metadata_file}")
        except Exception as e:
            logger.error(f"Erreur sauvegarde métadonnées: {e}")

    def __enter__(self):
        if not self.initialize():
            raise RuntimeError("Initialization failed")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.shutdown()
