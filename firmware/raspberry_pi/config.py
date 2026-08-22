"""
Configuration pour Horaltscanner - Raspberry Pi + Creality V4.2.2
Basée sur printer.cfg
"""

# ============================================================
#   CONFIGURATION USB
# ============================================================

USB_DEVICE_VID = 0x1A86  # Creality V4.2.2
USB_DEVICE_PID = 0x7523  # USB Serial
USB_BAUDRATE = 115200
USB_TIMEOUT = 5.0  # secondes

# Peut être auto-détecté ou spécifié manuellement
USB_PORT = "/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0"

# ============================================================
#   GPIO RASPBERRY PI (BCM)
# ============================================================

# Lasers
GPIO_LASER_GAUCHE = 27
GPIO_LASER_DROIT = 22

# LED RGB PWM
GPIO_RGB_R = 18
GPIO_RGB_G = 13
GPIO_RGB_B = 19

# Ventilateur Pi
GPIO_FAN_PI = 23

# ============================================================
#   PARAMÈTRES MOTEURS (du printer.cfg)
# ============================================================

MOTORS = {
    'X': {
        'name': 'Axe X - Translation avant/arrière',
        'microsteps': 16,
        'rotation_distance': 40,  # mm
        'max_velocity': 300,  # mm/s
        'max_accel': 3000,  # mm/s²
        'position_min': 0,
        'position_max': 210,  # mm
        'homing_speed': 50,  # mm/s
    },
    'Y': {
        'name': 'Axe Y - Plateau rotatif',
        'microsteps': 16,
        'rotation_distance': 620,  # mm (circumférence 20cm)
        'max_velocity': 300,  # mm/s
        'max_accel': 3000,  # mm/s²
        'position_min': 0,
        'position_max': 628.32,  # mm (full rotation)
        'homing_speed': 90,  # mm/s
    },
    'Z': {
        'name': 'Axe Z - Montée/descente',
        'microsteps': 16,
        'rotation_distance': 8,  # mm
        'max_velocity': 5,  # mm/s
        'max_accel': 100,  # mm/s²
        'position_min': 0,
        'position_max': 270,  # mm
        'homing_speed': 50,  # mm/s
    },
}

# Nombre de steps par rotation moteur NEMA17 standard
STEPS_PER_ROTATION = 200

# ============================================================
#   CALIBRATION CAMÉRAS / LIDAR
# ============================================================

CAMERAS = {
    'pi_v3_noir': {
        'interface': 'DSI',
        'location': 'droite',
        'description': 'Pi Camera V3 NoIR',
    },
    'logitech_c270': {
        'interface': 'USB',
        'location': 'gauche',
        'description': 'Webcam Logitech C270',
    },
}

LIDAR = {
    'tf_luna': {
        'interface': 'USB',
        'baudrate': 115200,
        'description': 'LiDAR TF-Luna',
    },
}

# ============================================================
#   LOGGING
# ============================================================

LOG_LEVEL = "INFO"  # DEBUG, INFO, WARNING, ERROR
LOG_FILE = "/var/log/horaltscanner.log"

# ============================================================
#   SCAN PARAMETERS
# ============================================================

# Exemple: paramètres de scan par défaut
DEFAULT_SCAN = {
    'rotation_steps': 360,  # full rotation en steps
    'z_positions': [0, 50, 100, 150],  # hauteurs de capture en mm
    'laser_duration': 100,  # ms
    'camera_capture_delay': 50,  # ms après laser
}
