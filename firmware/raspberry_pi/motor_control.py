"""
Motor Control - Orchestration des moteurs X/Y/Z
Wrapper haut niveau autour du driver USB
"""

import logging
import time
from typing import Optional, Dict
from .usb_driver import USBDriver
from . import config

logger = logging.getLogger(__name__)


class MotorController:
    """Contrôleur de moteurs pour les 3 axes du scanner"""

    def __init__(self, usb_driver: USBDriver):
        """
        Initialiser le contrôleur de moteurs
        
        Args:
            usb_driver: Instance du driver USB
        """
        self.usb = usb_driver
        self.state = {
            'X': {'position': 0.0, 'homed': False},
            'Y': {'position': 0.0, 'homed': False},
            'Z': {'position': 0.0, 'homed': False},
        }

    def home_all(self) -> bool:
        """
        Homing de tous les axes (X, Y, Z)
        
        Returns:
            True si tous les axes sont homed
        """
        logger.info("Démarrage homing tous les axes...")
        
        for axis in ['X', 'Y', 'Z']:
            if not self.home(axis):
                logger.error(f"Homing {axis} échoué")
                return False
                
        logger.info("Homing complété avec succès")
        return True

    def home(self, axis: str) -> bool:
        """
        Homing d'un axe unique
        
        Args:
            axis: 'X', 'Y' ou 'Z'
            
        Returns:
            True si succès
        """
        if axis not in config.MOTORS:
            logger.error(f"Axe invalide: {axis}")
            return False

        logger.info(f"Homing axe {axis}...")
        
        if self.usb.home(axis):
            self.state[axis]['homed'] = True
            self.state[axis]['position'] = config.MOTORS[axis]['position_min']
            logger.info(f"Axe {axis} homé")
            return True
        else:
            logger.error(f"Homing {axis} échoué")
            return False

    def move_abs(self, axis: str, position_mm: float) -> bool:
        """
        Mouvement absolu en mm
        
        Args:
            axis: 'X', 'Y' ou 'Z'
            position_mm: Position cible en mm
            
        Returns:
            True si succès
        """
        if axis not in config.MOTORS:
            logger.error(f"Axe invalide: {axis}")
            return False

        motor_cfg = config.MOTORS[axis]
        current_pos = self.state[axis]['position']

        # Vérifier les limites
        if not (motor_cfg['position_min'] <= position_mm <= motor_cfg['position_max']):
            logger.error(f"{axis}: Position {position_mm}mm hors limites "
                        f"[{motor_cfg['position_min']}, {motor_cfg['position_max']}]")
            return False

        # Calculer steps
        delta_mm = position_mm - current_pos
        steps = self._mm_to_steps(axis, delta_mm)
        speed = self._get_step_speed(axis, motor_cfg['homing_speed'])

        logger.debug(f"{axis}: Mouvement absolu {current_pos}mm → {position_mm}mm ({steps} steps)")

        if self.usb.move(axis, steps, speed):
            self.state[axis]['position'] = position_mm
            return True
        else:
            logger.error(f"Mouvement {axis} échoué")
            return False

    def move_rel(self, axis: str, delta_mm: float) -> bool:
        """
        Mouvement relatif en mm
        
        Args:
            axis: 'X', 'Y' ou 'Z'
            delta_mm: Déplacement relatif en mm
            
        Returns:
            True si succès
        """
        new_pos = self.state[axis]['position'] + delta_mm
        return self.move_abs(axis, new_pos)

    def move_steps(self, axis: str, steps: int) -> bool:
        """
        Mouvement en nombre de steps
        
        Args:
            axis: 'X', 'Y' ou 'Z'
            steps: Nombre de steps
            
        Returns:
            True si succès
        """
        if axis not in config.MOTORS:
            logger.error(f"Axe invalide: {axis}")
            return False

        motor_cfg = config.MOTORS[axis]
        speed = self._get_step_speed(axis, motor_cfg['homing_speed'])

        logger.debug(f"{axis}: Mouvement {steps} steps")

        if self.usb.move(axis, steps, speed):
            # Mettre à jour position
            delta_mm = self._steps_to_mm(axis, steps)
            self.state[axis]['position'] += delta_mm
            return True
        else:
            logger.error(f"Mouvement steps {axis} échoué")
            return False

    def get_state(self) -> Dict:
        """Récupérer l'état actuel des moteurs"""
        return dict(self.state)

    def is_homed(self, axis: str = None) -> bool:
        """
        Vérifier si un axe (ou tous) est homé
        
        Args:
            axis: 'X', 'Y', 'Z' ou None pour tous
            
        Returns:
            True si homé
        """
        if axis is None:
            return all(self.state[ax]['homed'] for ax in ['X', 'Y', 'Z'])
        return self.state[axis]['homed']

    # ============================================================
    #   HELPERS PRIVÉS
    # ============================================================

    def _mm_to_steps(self, axis: str, distance_mm: float) -> int:
        """Convertir mm en steps"""
        motor_cfg = config.MOTORS[axis]
        steps_per_mm = (config.STEPS_PER_ROTATION * motor_cfg['microsteps']) / motor_cfg['rotation_distance']
        return int(distance_mm * steps_per_mm)

    def _steps_to_mm(self, axis: str, steps: int) -> float:
        """Convertir steps en mm"""
        motor_cfg = config.MOTORS[axis]
        steps_per_mm = (config.STEPS_PER_ROTATION * motor_cfg['microsteps']) / motor_cfg['rotation_distance']
        return steps / steps_per_mm

    def _get_step_speed(self, axis: str, max_velocity_mm_s: float) -> int:
        """Convertir mm/s en steps/s"""
        motor_cfg = config.MOTORS[axis]
        steps_per_mm = (config.STEPS_PER_ROTATION * motor_cfg['microsteps']) / motor_cfg['rotation_distance']
        return int(max_velocity_mm_s * steps_per_mm)
