"""
USB Driver - Communication bas niveau avec le firmware STM32F103
Protocole texte CDC sur USB serial
"""

import serial
import logging
import re
import time
from typing import Optional, Dict, List
from enum import Enum

logger = logging.getLogger(__name__)


class CommandStatus(Enum):
    """Status des commandes"""
    SUCCESS = "OK"
    ERROR = "ERR"
    UNKNOWN = "UNKNOWN"


class USBDriver:
    """Driver USB CDC pour communication avec STM32F103 (Creality V4.2.2)"""

    def __init__(self, port: str = "/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0",
                 baudrate: int = 115200, timeout: float = 5.0):
        """
        Initialiser la connexion USB
        
        Args:
            port: Port série USB
            baudrate: Vitesse de communication (115200)
            timeout: Timeout en secondes
        """
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.ser = None
        self.connected = False

    def connect(self) -> bool:
        """Établir la connexion USB"""
        try:
            self.ser = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=self.timeout,
                write_timeout=self.timeout
            )
            self.connected = True
            logger.info(f"USB connecté: {self.port} @ {self.baudrate} baud")
            
            # Ping de test
            if self.ping():
                logger.info("Handshake réussi")
                return True
            else:
                logger.warning("Handshake failed - firmware may not be responding")
                return False
                
        except serial.SerialException as e:
            logger.error(f"Erreur connexion USB: {e}")
            self.connected = False
            return False

    def disconnect(self) -> None:
        """Fermer la connexion USB"""
        if self.ser and self.ser.is_open:
            self.ser.close()
            self.connected = False
            logger.info("USB déconnecté")

    def send_command(self, command: str) -> Optional[str]:
        """
        Envoyer une commande et récupérer la réponse
        
        Args:
            command: Commande à envoyer (ex: "PING", "MOVE X 100 50")
            
        Returns:
            Réponse du firmware (sans newline) ou None en cas d'erreur
        """
        if not self.connected or not self.ser:
            logger.error("USB non connecté")
            return None

        try:
            # Envoyer la commande avec newline
            cmd_bytes = (command + "\n").encode('utf-8')
            self.ser.write(cmd_bytes)
            logger.debug(f"TX: {command}")
            
            # Lire la réponse
            response = self._read_response()
            if response:
                logger.debug(f"RX: {response}")
            return response
            
        except serial.SerialException as e:
            logger.error(f"Erreur envoi commande: {e}")
            self.connected = False
            return None

    def _read_response(self) -> Optional[str]:
        """
        Lire une ligne de réponse depuis le firmware
        
        Returns:
            Ligne sans newline ou None si timeout
        """
        try:
            line = self.ser.readline().decode('utf-8').strip()
            if line:
                return line
            return None
        except (serial.SerialException, UnicodeDecodeError) as e:
            logger.error(f"Erreur lecture réponse: {e}")
            return None

    def _parse_response(self, response: str) -> tuple[CommandStatus, str]:
        """
        Parser la réponse du firmware
        
        Format attendu: "OK <payload>" ou "ERR <reason>"
        
        Returns:
            (status, payload)
        """
        if not response:
            return CommandStatus.UNKNOWN, ""

        parts = response.split(maxsplit=1)
        status_str = parts[0]
        payload = parts[1] if len(parts) > 1 else ""

        if status_str == "OK":
            return CommandStatus.SUCCESS, payload
        elif status_str == "ERR":
            return CommandStatus.ERROR, payload
        else:
            return CommandStatus.UNKNOWN, response

    # ============================================================
    #   COMMANDES FIRMWARE
    # ============================================================

    def ping(self) -> bool:
        """Test de connectivité"""
        response = self.send_command("PING")
        status, payload = self._parse_response(response)
        return status == CommandStatus.SUCCESS and "PONG" in payload

    def move(self, axis: str, steps: int, speed: int) -> bool:
        """
        Déplacer un moteur
        
        Args:
            axis: 'X', 'Y' ou 'Z'
            steps: Nombre de steps (positif=avance, négatif=recul)
            speed: Vitesse en steps/s (simplifié)
            
        Returns:
            True si succès
        """
        if axis not in ['X', 'Y', 'Z']:
            logger.error(f"Axe invalide: {axis}")
            return False

        command = f"MOVE {axis} {steps} {speed}"
        response = self.send_command(command)
        status, _ = self._parse_response(response)
        return status == CommandStatus.SUCCESS

    def home(self, axis: str) -> bool:
        """
        Homing d'un axe
        
        Args:
            axis: 'X', 'Y' ou 'Z'
            
        Returns:
            True si succès
        """
        if axis not in ['X', 'Y', 'Z']:
            logger.error(f"Axe invalide: {axis}")
            return False

        command = f"HOME {axis}"
        response = self.send_command(command)
        status, _ = self._parse_response(response)
        if status == CommandStatus.SUCCESS:
            logger.info(f"Homing {axis} réussi")
            return True
        else:
            logger.error(f"Homing {axis} échoué")
            return False

    def get_endstop(self, axis: str) -> Optional[bool]:
        """
        Lire l'état d'un endstop
        
        Args:
            axis: 'X', 'Y' ou 'Z'
            
        Returns:
            True (déclenché), False (non déclenché), None (erreur)
        """
        if axis not in ['X', 'Y', 'Z']:
            logger.error(f"Axe invalide: {axis}")
            return None

        command = f"ENDSTOP {axis}"
        response = self.send_command(command)
        status, payload = self._parse_response(response)
        
        if status == CommandStatus.SUCCESS:
            # Parser "ENDSTOP 0" ou "ENDSTOP 1"
            match = re.search(r"ENDSTOP (\d)", payload)
            if match:
                return bool(int(match.group(1)))
        
        return None

    def get_status(self) -> Optional[Dict]:
        """
        Lire l'état complet du scanner
        
        Returns:
            Dict avec positions et flags homing, ou None
        """
        response = self.send_command("STATUS")
        status, payload = self._parse_response(response)
        
        if status == CommandStatus.SUCCESS:
            # Parser "X:0.00 Y:0.00 Z:0.00 HX:0 HY:0 HZ:0"
            result = {}
            for part in payload.split():
                if ':' in part:
                    key, value = part.split(':')
                    try:
                        result[key] = float(value) if '.' in value else int(value)
                    except ValueError:
                        pass
            return result if result else None
        
        return None

    def sync(self, token: str) -> Optional[str]:
        """
        Synchronisation avec token
        
        Args:
            token: Token de synchronisation
            
        Returns:
            Token reçu ou None en cas d'erreur
        """
        command = f"SYNC {token}"
        response = self.send_command(command)
        status, payload = self._parse_response(response)
        
        if status == CommandStatus.SUCCESS:
            # Parser "SYNC <token>"
            match = re.search(r"SYNC\s+(\S+)", payload)
            if match:
                return match.group(1)
        
        return None

    def execute_sequence(self, commands: List[tuple]) -> bool:
        """
        Exécuter une séquence de commandes
        
        Args:
            commands: Liste de tuples (type, args...)
                      ex: [('MOVE', 'X', 100, 50), ('HOME', 'Y'), ...]
                      
        Returns:
            True si toutes les commandes réussissent
        """
        for cmd_tuple in commands:
            cmd_type = cmd_tuple[0]
            
            if cmd_type == "MOVE":
                _, axis, steps, speed = cmd_tuple
                if not self.move(axis, steps, speed):
                    return False
                    
            elif cmd_type == "HOME":
                _, axis = cmd_tuple
                if not self.home(axis):
                    return False
                    
            elif cmd_type == "WAIT":
                _, delay_ms = cmd_tuple
                time.sleep(delay_ms / 1000.0)
                
            else:
                logger.warning(f"Type de commande inconnu: {cmd_type}")
                
        return True

    def __enter__(self):
        """Context manager entry"""
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        self.disconnect()
