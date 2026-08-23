"""
Camera Acquisition - Gestion des caméras Pi V3 et Logitech C270
Capture et stockage des images de scan
"""

import logging
import time
from pathlib import Path
from typing import Optional, Tuple, List
from enum import Enum
from datetime import datetime
import threading
from queue import Queue

try:
    import cv2
    OPENCV_AVAILABLE = True
except ImportError:
    OPENCV_AVAILABLE = False
    logging.warning("OpenCV non disponible - acquisition caméra en mode simulation")

try:
    from picamera2 import Picamera2
    PICAMERA_AVAILABLE = True
except ImportError:
    PICAMERA_AVAILABLE = False
    logging.warning("picamera2 non disponible - caméra Pi en mode simulation")

logger = logging.getLogger(__name__)


class CameraType(Enum):
    """Type de caméra"""
    PI_V3_NOIR = "pi_v3_noir"
    LOGITECH_C270 = "logitech_c270"


class CameraCapture:
    """Gestion d'une caméra unique"""

    def __init__(self, camera_type: CameraType, output_dir: Path = None):
        """
        Initialiser la capture caméra
        
        Args:
            camera_type: Type de caméra
            output_dir: Répertoire de sortie pour les images
        """
        self.camera_type = camera_type
        self.output_dir = Path(output_dir or f"/tmp/horaltscanner_scan_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        self.camera = None
        self.is_connected = False
        self.frame_count = 0
        
        if camera_type == CameraType.PI_V3_NOIR:
            self._init_pi_camera()
        elif camera_type == CameraType.LOGITECH_C270:
            self._init_usb_camera()

    def _init_pi_camera(self) -> None:
        """Initialiser la caméra Raspberry Pi V3 NoIR (DSI)"""
        if not PICAMERA_AVAILABLE:
            logger.warning("picamera2 non disponible - mode simulation")
            self.is_connected = True
            return
        
        try:
            self.camera = Picamera2()
            config = self.camera.create_preview_configuration(
                main={"format": "RGB888", "size": (1920, 1080)}
            )
            self.camera.configure(config)
            self.camera.start()
            self.is_connected = True
            logger.info("Caméra Pi V3 NoIR initialisée")
        except Exception as e:
            logger.error(f"Erreur initialisation caméra Pi: {e}")
            self.is_connected = False

    def _init_usb_camera(self) -> None:
        """Initialiser la caméra USB Logitech C270"""
        if not OPENCV_AVAILABLE:
            logger.warning("OpenCV non disponible - mode simulation")
            self.is_connected = True
            return
        
        try:
            # Essayer différents index pour trouver la caméra USB
            for idx in range(5):
                cap = cv2.VideoCapture(idx)
                if cap.isOpened():
                    # Vérifier que c'est bien une caméra (pas une autre device)
                    ret, frame = cap.read()
                    if ret and frame is not None:
                        self.camera = cap
                        self.is_connected = True
                        logger.info(f"Caméra USB Logitech trouvée sur /dev/video{idx}")
                        return
                    cap.release()
            
            logger.error("Aucune caméra USB trouvée")
            self.is_connected = False
        except Exception as e:
            logger.error(f"Erreur initialisation caméra USB: {e}")
            self.is_connected = False

    def capture(self, filename: str = None) -> Optional[Path]:
        """
        Capturer une image
        
        Args:
            filename: Nom du fichier (auto-généré si None)
            
        Returns:
            Path de l'image sauvegardée ou None
        """
        if not self.is_connected:
            logger.warning(f"{self.camera_type.value}: Caméra non connectée")
            return None
        
        if filename is None:
            filename = f"{self.camera_type.value}_{self.frame_count:05d}.png"
        
        filepath = self.output_dir / filename
        
        try:
            if self.camera_type == CameraType.PI_V3_NOIR:
                self._capture_pi(filepath)
            else:
                self._capture_usb(filepath)
            
            self.frame_count += 1
            logger.debug(f"Image capturée: {filepath}")
            return filepath
        except Exception as e:
            logger.error(f"Erreur capture image: {e}")
            return None

    def _capture_pi(self, filepath: Path) -> None:
        """Capturer avec caméra Pi"""
        if not PICAMERA_AVAILABLE or self.camera is None:
            logger.debug(f"[SIM] Capture Pi: {filepath}")
            return
        
        try:
            array = self.camera.capture_array()
            import numpy as np
            # Sauvegarder avec OpenCV si disponible
            if OPENCV_AVAILABLE:
                cv2.imwrite(str(filepath), cv2.cvtColor(array, cv2.COLOR_RGB2BGR))
            else:
                # Fallback: scipy ou PIL
                from PIL import Image
                Image.fromarray(array).save(filepath)
        except Exception as e:
            logger.error(f"Erreur capture Pi: {e}")

    def _capture_usb(self, filepath: Path) -> None:
        """Capturer avec caméra USB"""
        if not OPENCV_AVAILABLE or self.camera is None:
            logger.debug(f"[SIM] Capture USB: {filepath}")
            return
        
        ret, frame = self.camera.read()
        if ret:
            cv2.imwrite(str(filepath), frame)
        else:
            raise RuntimeError("Impossible de lire frame caméra USB")

    def disconnect(self) -> None:
        """Fermer la caméra"""
        if self.camera:
            try:
                if self.camera_type == CameraType.PI_V3_NOIR and PICAMERA_AVAILABLE:
                    self.camera.stop()
                elif OPENCV_AVAILABLE:
                    self.camera.release()
            except Exception as e:
                logger.warning(f"Erreur fermeture caméra: {e}")
        
        self.is_connected = False
        logger.info(f"{self.camera_type.value} fermée")


class DualCameraSystem:
    """Système dual-caméra coordonnée"""

    def __init__(self, output_dir: Path = None, capture_mode: str = "synchronized"):
        """
        Initialiser le système dual-caméra
        
        Args:
            output_dir: Répertoire de sortie
            capture_mode: "synchronized" ou "independent"
        """
        self.output_dir = Path(output_dir or f"/tmp/horaltscanner_scan_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        self.capture_mode = capture_mode
        self.pi_camera = None
        self.usb_camera = None
        self.initialized = False
        
        self._init_cameras()

    def _init_cameras(self) -> None:
        """Initialiser les deux caméras"""
        logger.info("Initialisation système dual-caméra...")
        
        try:
            # Caméra Pi
            self.pi_camera = CameraCapture(
                CameraType.PI_V3_NOIR,
                output_dir=self.output_dir / "pi_v3"
            )
            
            # Caméra USB
            self.usb_camera = CameraCapture(
                CameraType.LOGITECH_C270,
                output_dir=self.output_dir / "usb_logitech"
            )
            
            if self.pi_camera.is_connected and self.usb_camera.is_connected:
                self.initialized = True
                logger.info("Système dual-caméra prêt")
            else:
                logger.warning(f"Caméra Pi: {self.pi_camera.is_connected}, USB: {self.usb_camera.is_connected}")
        except Exception as e:
            logger.error(f"Erreur initialisation caméras: {e}")
            self.initialized = False

    def capture_pair(self, position_name: str = None) -> Tuple[Optional[Path], Optional[Path]]:
        """
        Capturer une paire d'images synchronisées
        
        Args:
            position_name: Nom de la position (ex: "scan_001")
            
        Returns:
            (chemin_pi, chemin_usb) ou (None, None)
        """
        if not self.initialized:
            logger.error("Système non initialisé")
            return None, None
        
        if position_name is None:
            position_name = f"position_{self.pi_camera.frame_count:05d}"
        
        # Capturer les deux caméras
        if self.capture_mode == "synchronized":
            # Synchronisé: capturer presque simultanément
            pi_path = self.pi_camera.capture(f"{position_name}_pi.png")
            usb_path = self.usb_camera.capture(f"{position_name}_usb.png")
        else:
            # Indépendant
            pi_path = self.pi_camera.capture(f"{position_name}_pi.png")
            usb_path = self.usb_camera.capture(f"{position_name}_usb.png")
        
        return pi_path, usb_path

    def get_frame_count(self) -> Tuple[int, int]:
        """Récupérer le nombre de frames capturées"""
        return self.pi_camera.frame_count if self.pi_camera else 0, \
               self.usb_camera.frame_count if self.usb_camera else 0

    def disconnect(self) -> None:
        """Fermer les deux caméras"""
        if self.pi_camera:
            self.pi_camera.disconnect()
        if self.usb_camera:
            self.usb_camera.disconnect()
        self.initialized = False
        logger.info("Système dual-caméra fermé")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()
