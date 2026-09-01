## ✅ Hotfix: actionneurs + caméra USB stabilisés

Cette mise à jour corrige et valide le pilotage matériel côté API/Web.

### Correctifs inclus

- **Web UI fans** : envoi du bon contrat JSON vers l’API  
  (`speed` en float `0.0..1.0`, au lieu de `enabled` booléen).
- **Caméra USB (Logitech/UVC)** :
  - fallback d’index à l’ouverture (`device_id` configuré puis `0,1,2,3`)
  - validation par lecture réelle d’image
  - sélection automatique du premier device valide
  - logs d’ouverture/échec plus clairs

### Validation manuelle effectuée (Raspberry Pi)

- **Lasers** : ON/OFF OK (`/api/laser/left`, `/api/laser/right`)
- **RGB** : couleurs OK (`/api/led/color`)
- **Fans** : contrôle vitesse OK (`/api/fan/creality`, `/api/fan/temperature`)
- **USB camera status** : `{"available":true,...}` OK
- **USB camera frame** : `HTTP/1.1 200 OK` + `Content-Type: image/jpeg`

### Commits principaux

- `cb524fc` — fix(web): send fan speed as 0.0..1.0 instead of enabled boolean
- `ac91f56` — fix(camera): USB fallback indices and read validation
