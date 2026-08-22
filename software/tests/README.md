# Horaltscanner Tests

Tests unitaires et d'intégration pour le scanner 3D USB.

## Structure

```
software/tests/
├── conftest.py              # Fixtures pytest communes
├── test_usb_driver.py       # Tests driver USB
├── test_motor_control.py    # Tests contrôleur moteurs
├── test_gpio_control.py     # Tests GPIO laser/LED/fan
└── test_scanner_app.py      # Tests app d'intégration
```

## Exécution

### Tous les tests
```bash
python -m pytest software/tests/ -v
```

### Tests spécifiques
```bash
python -m pytest software/tests/test_usb_driver.py -v
python -m pytest software/tests/test_motor_control.py -v
```

### Avec couverture de code
```bash
python -m pytest software/tests/ --cov=firmware/raspberry_pi --cov-report=html
```

### Mode verbose
```bash
python -m pytest software/tests/ -v -s
```

## Requirements

```
pytest>=7.0.0
pytest-cov>=3.0.0
pyserial>=3.5
gpiozero>=1.6.0  # optionnel (tests en simulation si non disponible)
```
