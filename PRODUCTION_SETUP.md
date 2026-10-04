# 🚀 Horaltscanner - Production Setup Guide (Raspberry Pi 4)

Guide complet pour déployer Horaltscanner en production sur Raspberry Pi 4 avec Gunicorn + systemd.

---

## 📋 Prerequisites

- Raspberry Pi 4 (4GB RAM minimum recommandé)
- Raspberry Pi OS Bookworm (64-bit recommandé)
- SSH accès à votre RPi
- `git` installé sur le RPi
- `python3-full` installé (`sudo apt install python3-full`)

---

## ✅ Step 1: Clone le repository

```bash
cd ~
git clone https://github.com/jose33bro/horaltscanner.git
cd horaltscanner
```

---

## ✅ Step 2: Crée un virtual environment

```bash
# Crée le venv
python3 -m venv ~/horaltscanner_env

# Active le venv
source ~/horaltscanner_env/bin/activate

# Upgrade pip
pip install --upgrade pip setuptools wheel
```

---

## ✅ Step 3: Installe les dépendances

```bash
# Depuis le repo directory (avec venv activé)
pip install -r requirements.txt
```

### ⚠️ Open3D sur ARM64

Si vous êtes sur **Raspberry Pi OS 64-bit**, Open3D n'a pas de wheels PyPI. Compilez-le:

```bash
bash software/scripts/install_open3d_pi.sh
```

(Cela prend ~30-60 minutes. Le script compile avec seulement 2 jobs pour économiser la mémoire)

---

## ✅ Step 4: Teste manuellement (optionnel)

Avant de déployer via systemd, testez que tout fonctionne:

```bash
# Depuis le repo root
cd software
gunicorn \
  --workers 1 \
  --worker-class sync \
  --bind 127.0.0.1:5000 \
  api:create_app

# Dans une autre fenêtre SSH:
curl http://localhost:5000/api/health
# Devrait répondre: {"status": "ok"}
```

Ctrl+C pour arrêter.

---

## ✅ Step 5: Crée le service systemd

Crée le fichier `/etc/systemd/system/horaltscanner.service`:

```bash
sudo tee /etc/systemd/system/horaltscanner.service > /dev/null <<'EOF'
[Unit]
Description=HoralScanner 3D Scanner API (Gunicorn)
After=network.target
Wants=network-online.target

[Service]
Type=notify
User=pi
WorkingDirectory=/home/pi/horaltscanner
Environment="PATH=/home/pi/horaltscanner_env/bin"
Environment="PYTHONUNBUFFERED=1"

# Un seul processus doit posseder le GPIO, les ports serie et les cameras.
# N'utilisez JAMAIS --worker-class gevent: le driver STM32/moteur fait des
# lectures bloquantes sur un port serie (pyserial), et le monkey-patching de
# gevent intercepte cette lecture comme s'il s'agissait d'un socket; l'attente
# cooperative ne se reveille alors plus jamais. Chaque requete qui touche le
# driver (meme /api/status) reste bloquee indefiniment. Confirme sur le
# materiel: gevent -> sync a transforme un blocage infini en reponse ~15ms.
ExecStart=/home/pi/horaltscanner_env/bin/gunicorn \
  --workers 1 \
  --worker-class sync \
  --bind 0.0.0.0:5000 \
  --access-logfile - \
  --error-logfile - \
  software.api:create_app

# Redémarrer automatiquement en cas de crash
Restart=always
RestartSec=10

# Logs
StandardOutput=journal
StandardError=journal
SyslogIdentifier=horaltscanner

# Sécurité
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
EOF
```

---

## ✅ Step 6: Active et démarre le service

```bash
# Recharge systemd
sudo systemctl daemon-reload

# Active au démarrage
sudo systemctl enable horaltscanner

# Démarre le service
sudo systemctl start horaltscanner

# Vérifie le statut
sudo systemctl status horaltscanner

# Vois les logs (dernières 50 lignes)
sudo journalctl -u horaltscanner -n 50 -f
```

---

## ✅ Step 7: Vérifie que ça marche

```bash
# Depuis votre machine locale (remplacez <pi-ip> par l'IP de votre RPi):
curl http://<pi-ip>:5000/api/health
# Devrait répondre: {"status": "ok"}

# Teste un scan simple via le dashboard:
# Ouvrez http://<pi-ip>:5000 dans un navigateur
```

---

## 📊 Monitoring

### Voir les logs en temps réel
```bash
sudo journalctl -u horaltscanner -f
```

### Redémarrer le service
```bash
sudo systemctl restart horaltscanner
```

### Arrêter le service
```bash
sudo systemctl stop horaltscanner
```

### Voir le statut
```bash
sudo systemctl status horaltscanner
```

---

## 🐛 Troubleshooting

### Port 5000 déjà utilisé
```bash
# Trouve quel processus l'utilise:
sudo lsof -i :5000

# Tue-le:
sudo kill -9 <PID>
```

### Import error: `ModuleNotFoundError: No module named 'gevent'`
```bash
# Réactive le venv et réinstalle les dépendances:
source ~/horaltscanner_env/bin/activate
pip install -r requirements.txt
sudo systemctl restart horaltscanner
```

### Reconstruction très lente / API freezes
- Vérifiez que vous utilisez **Gunicorn** (pas `python api/horalscanner_api.py`)
- Vérifiez que vous avez **1 worker** configuré; le matériel et l'état du scan ont un propriétaire unique
- Vérifiez que vous utilisez le worker class **sync** (pas `gevent` — voir ci-dessous)

### API `/api/status` ou toute route hang indéfiniment (timeout, aucune réponse)
- Cause confirmée sur matériel: `--worker-class gevent` casse les lectures
  bloquantes du driver STM32/moteur sur le port série (`pyserial`). Le
  monkey-patching de gevent intercepte la lecture TTY comme un socket, et
  l'attente coopérative ne se réveille jamais — même avec un `timeout_s`
  configuré côté pyserial.
- Solution: utilisez `--worker-class sync` (déjà fait dans ce guide). Avec
  1 seul worker, l'accès au matériel est de toute façon sérialisé par
  requête, donc gevent n'apporte aucun gain de concurrence ici.
- Si le service est déjà bloqué: `sudo fuser -k 5000/tcp` puis
  `sudo systemctl restart horaltscanner`.

### Open3D import error
```bash
# Vérifiez que Open3D est installé:
source ~/horaltscanner_env/bin/activate
python3 -c "import open3d; print(open3d.__version__)"

# Si erreur, compilez-le:
bash software/scripts/install_open3d_pi.sh
```

---

## 📈 Performance Tips

1. **1 worker** pour tout déploiement matériel:
   - Ne l'augmentez pas: GPIO, série, caméras et état du scan sont partagés
   - Utilisez le worker class **sync** (pas `gevent`, voir Dépannage) et les
     tâches d'arrière-plan pour conserver une API réactive

2. **Worker class `sync`**:
   - Un seul worker sérialise déjà l'accès au matériel par requête
   - Les captures d'image, uploads, et reads API passent par des locks explicites
   - Le Poisson reconstruction tourne en background thread

3. **Asynchronous reconstruction** (PR #83):
   - `POST /api/model/reconstruct` retourne immédiatement
   - Poll `GET /api/model/status` pour voir la progression
   - N'utilise plus de temp files (bytesIO in-memory)

4. **Bounded point cloud** (PR #82):
   - Max 200k points (~500MB)
   - Les anciens points sont auto-droppés (FIFO)
   - Pas de crash OOM sur long scans

---

## 🔄 Mise à Jour

Pour mettre à jour le code:

```bash
cd ~/horaltscanner
git pull origin main
source ~/horaltscanner_env/bin/activate
pip install -r requirements.txt
sudo systemctl restart horaltscanner
```

---

## 📝 Logs et Debugging

### Logs du service
```bash
sudo journalctl -u horaltscanner -n 100 --no-pager
```

### Logs en temps réel
```bash
sudo journalctl -u horaltscanner -f
```

### Logs depuis une date
```bash
sudo journalctl -u horaltscanner --since "2026-09-02 14:00:00"
```

---

## 🎯 Vérification Finale

Une fois déployé, vérifiez:

- [ ] Service démarre au boot: `sudo systemctl is-enabled horaltscanner` → `enabled`
- [ ] Service tourne: `sudo systemctl is-active horaltscanner` → `active`
- [ ] API répond: `curl http://localhost:5000/api/health` → `{"status": "ok"}`
- [ ] Dashboard accessible: `http://<pi-ip>:5000` dans un navigateur
- [ ] Reconstruction non-bloquante: lancez un scan, puis poll `/api/model/status`

---

## 💡 Notes

- **Flask dev server** (`python api/horalscanner_api.py`) est **JAMAIS** production-ready car:
  - Single-threaded → blocage si reconstruction, capture, ou UI requête concurrente
  - Pas de gestion gracieuse des erreurs
  - Pas de logging structuré
  - Pas de gestion des signaux (SIGTERM, etc.)

- **Gunicorn** résout tout cela:
  - Worker sync dédié au matériel (1 process, requêtes sérialisées)
  - Graceful shutdown + restart
  - Logging structuré via systemd journal

---

**Horaltscanner est maintenant en production sur votre RPi4! 🚀**
