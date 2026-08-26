# Firmware HoralScanner pour Creality V4.2.2

Ce firmware cible uniquement une carte Creality V4.2.2 équipée d'un
**STM32F103RET6**. Il implémente le protocole décrit dans
`docs/usb_protocol.md` sur le CH340 de la carte à 115200 bauds.

## Sécurité

- Les sorties chauffantes PA1 et PA2 sont forcées à l'arrêt.
- Les moteurs sont désactivés au démarrage, après chaque mouvement et après
  cinq secondes sans commande.
- Un déplacement vers la butée s'arrête dès que l'entrée correspondante passe
  à l'état bas.
- Une recherche d'origine est abandonnée après 120 secondes.
- Les mouvements utilisent une rampe d'accélération et de décélération pour
  éviter les résonances et pertes de pas du plateau.
- La vitesse de référencement est limitée séparément pour chaque mécanique:
  X et Z à 400 pas/s, Y à 100 pas/s après accélération progressive.
- Les trois axes partagent la sortie d'activation PC3.

Ne flashez pas ce binaire sur une carte GD32 ou une autre révision. Débranchez
les moteurs avant le premier test de communication. Vérifiez ensuite chaque
fin de course avec `ENDSTOP X`, `ENDSTOP Y` et `ENDSTOP Z` avant d'utiliser
`HOME`.

## Compilation

Depuis la racine du dépôt:

```bash
bash software/scripts/build_creality_firmware.sh
```

Le binaire est créé dans:

```text
firmware/creality_v422/build/firmware.bin
```

Le linker place l'application à `0x08007000`, après le bootloader Creality de
28 Kio. La table des vecteurs est déplacée au même endroit.

## Flash par carte microSD

1. Utilisez une carte microSD FAT32 de 8 Go ou moins.
2. Copiez uniquement le binaire à la racine, sous le nom `firmware.bin`.
3. Coupez complètement l'alimentation 24 V et débranchez l'USB.
4. Insérez la microSD, puis remettez l'alimentation 24 V.
5. Attendez 30 secondes sans couper l'alimentation.
6. Coupez l'alimentation, retirez la carte, puis reconnectez l'USB.

Le fichier est généralement renommé `FIRMWARE.CUR` après un flash réussi.
Après reconnexion au Raspberry Pi:

```bash
sudo systemctl stop horalscanner
sudo /home/pi/horaltscanner_env/bin/python3 -c \
  "import serial,time; s=serial.Serial('/dev/ttyUSB0',115200,timeout=2); time.sleep(2); s.write(b'PING\n'); s.flush(); print(repr(s.readline())); s.close()"
sudo systemctl restart horalscanner
```

La réponse attendue est `b'OK PONG\r\n'`.
