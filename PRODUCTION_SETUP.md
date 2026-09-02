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
  --workers 2 \
  --worker-class gevent \
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
Description=HoralScanner 3D Scanner API (Gunicorn + Gevent)
After=network.target
Wants=network-online.target

[Service]
Type=notify
User=pi
WorkingDirectory=/home/pi/horaltscanner
Environment="PATH=/home/pi/horaltscanner_env/bin"
Environment="PYTHONUNBUFFERED=1"

# Un seul processus doit posseder le GPIO, les ports serie et les cameras.
ExecStart=/home/pi/horaltscanner_env/bin/gunicorn \
  --workers 1 \
  --worker-class gevent \
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
- Vérifiez que vous avez **4 workers** configurés
- Vérifiez que vous utilisez **gevent** worker class (non-bloquant)

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

1. **4 workers** pour RPi4 4GB: bon équilibre entre concurrence et mémoire
   - Augmentez à 8 si vous avez 8GB RAM
   - Diminuez à 2 si vous avez moins de 2GB RAM

2. **Gevent worker class** élimine le blocage I/O:
   - Les captures d'image, uploads, et reads API deviennent async
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

- **Gunicorn + gevent** résout tout cela:
  - Multi-worker concurrence
  - Gevent rend I/O et threads non-bloquants
  - Graceful shutdown + restart
  - Logging structuré via systemd journal

---

**Horaltscanner est maintenant en production sur votre RPi4! 🚀**
