"""
LiDAR Acquisition - Gestion du capteur LiDAR TF-Luna
Capture et stockage des données de distance
"""

import logging
import serial
import struct
from pathlib import Path
from typing import Optional, List, Tuple
from datetime import datetime
from collections import deque

logger = logging.getLogger(__name__)


class TFLunaLiDAR:
    """Pilote pour LiDAR TF-Luna via USB"""

    # Frame format TF-Luna
    FRAME_START = 0x59
    FRAME_LENGTH = 9  # bytes
    
    def __init__(self, port: str = "/dev/ttyUSB1", baudrate: int = 115200):
        """
        Initialiser le LiDAR TF-Luna
        
        Args:
            port: Port série USB
            baudrate: Vitesse de communication
        """
        self.port = port
        self.baudrate = baudrate
        self.ser = None
        self.connected = False
        self.measurement_count = 0
        
    def connect(self) -> bool:
        """Établir la connexion avec le LiDAR"""
        try:
            self.ser = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=1.0
            )
            self.connected = True
            logger.info(f"LiDAR TF-Luna connecté: {self.port}")
            return True
        except serial.SerialException as e:
            logger.error(f"Erreur connexion LiDAR: {e}")
            self.connected = False
            return False

    def disconnect(self) -> None:
        """Fermer la connexion"""
        if self.ser and self.ser.is_open:
            self.ser.close()
        self.connected = False
        logger.info("LiDAR TF-Luna déconnecté")

    def read_measurement(self) -> Optional[Tuple[int, int, int]]:
        """
        Lire une mesure du LiDAR
        
        Format TF-Luna:
        - Byte 0-1: 0x59 0x59 (start)
        - Byte 2-3: Distance (mm) little-endian
        - Byte 4-5: Strength (0-65535)
        - Byte 6: Temperature (°C offset)
        - Byte 7: Checksum
        
        Returns:
            (distance_mm, strength, temperature_c) ou None
        """
        if not self.connected or not self.ser:
            return None
        
        try:
            # Attendre le start frame
            while True:
                byte = self.ser.read(1)
                if not byte:
                    return None
                if byte[0] == self.FRAME_START:
                    # Lire le deuxième start byte
                    byte2 = self.ser.read(1)
                    if byte2 and byte2[0] == self.FRAME_START:
                        break
            
            # Lire le reste du frame (7 bytes)
            frame = self.ser.read(7)
            if len(frame) < 7:
                return None
            
            # Parser les données
            distance = struct.unpack('<H', frame[0:2])[0]  # Distance en mm
            strength = struct.unpack('<H', frame[2:4])[0]  # Intensité signal
            temp_raw = frame[4]
            temp_c = temp_raw - 40  # Température en °C
            checksum = frame[5]
            
            # Vérifier checksum (optionnel)
            # calculated_checksum = (0x59 + 0x59 + distance_l + distance_h + strength_l + strength_h + temp_raw) & 0xFF
            
            self.measurement_count += 1
            return distance, strength, temp_c
            
        except Exception as e:
            logger.error(f"Erreur lecture LiDAR: {e}")
            return None

    def read_multiple(self, count: int = 10) -> List[Tuple[int, int, int]]:
        """
        Lire plusieurs mesures
        
        Args:
            count: Nombre de mesures à lire
            
        Returns:
            Liste de (distance, strength, temperature)
        """
        measurements = []
        for _ in range(count):
            measurement = self.read_measurement()
            if measurement:
                measurements.append(measurement)
        return measurements

    def get_statistics(self, measurements: List[Tuple[int, int, int]]) -> dict:
        """
        Calculer des statistiques sur les mesures
        
        Args:
            measurements: Liste de mesures
            
        Returns:
            Dict avec min/max/mean distance, signal strength
        """
        if not measurements:
            return {}
        
        distances = [m[0] for m in measurements]
        strengths = [m[1] for m in measurements]
        temperatures = [m[2] for m in measurements]
        
        return {
            'distance_min': min(distances),
            'distance_max': max(distances),
            'distance_mean': sum(distances) / len(distances),
            'strength_min': min(strengths),
            'strength_max': max(strengths),
            'strength_mean': sum(strengths) / len(strengths),
            'temperature_mean': sum(temperatures) / len(temperatures),
        }

    def save_measurements(self, measurements: List[Tuple[int, int, int]], 
                         filepath: Path) -> None:
        """
        Sauvegarder les mesures dans un fichier CSV
        
        Args:
            measurements: Liste de mesures
            filepath: Chemin du fichier de sortie
        """
        try:
            filepath = Path(filepath)
            filepath.parent.mkdir(parents=True, exist_ok=True)
            
            with open(filepath, 'w') as f:
                f.write("distance_mm,strength,temperature_c\n")
                for distance, strength, temp in measurements:
                    f.write(f"{distance},{strength},{temp}\n")
            
            logger.info(f"Mesures LiDAR sauvegardées: {filepath}")
        except Exception as e:
            logger.error(f"Erreur sauvegarde mesures: {e}")


class LiDARFrameBuffer:
    """Buffer circulaire pour les mesures LiDAR"""

    def __init__(self, max_size: int = 1000):
        """
        Initialiser le buffer
        
        Args:
            max_size: Taille maximale du buffer
        """
        self.buffer = deque(maxlen=max_size)
        self.max_size = max_size

    def add(self, measurement: Tuple[int, int, int]) -> None:
        """Ajouter une mesure"""
        self.buffer.append(measurement)

    def get_all(self) -> List[Tuple[int, int, int]]:
        """Récupérer toutes les mesures"""
        return list(self.buffer)

    def clear(self) -> None:
        """Vider le buffer"""
        self.buffer.clear()

    def size(self) -> int:
        """Nombre de mesures actuelles"""
        return len(self.buffer)

    def is_full(self) -> bool:
        """Buffer plein?"""
        return len(self.buffer) == self.max_size
