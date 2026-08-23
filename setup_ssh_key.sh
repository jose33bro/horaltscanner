#!/bin/bash
# setup_ssh_key.sh - Script pour configurer une clé SSH sur le Pi
# À exécuter d'abord sur votre ordinateur, puis sur le Pi

set -e

echo "========================================"
echo "Configuration SSH pour Horaltscanner"
echo "========================================"
echo ""

# Détecter le système
if [[ "$OSTYPE" == "darwin"* ]]; then
    SSH_DIR="$HOME/.ssh"
    OPEN_CMD="open"
elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
    SSH_DIR="$HOME/.ssh"
    OPEN_CMD="xdg-open"
else
    SSH_DIR="$HOME/.ssh"
    OPEN_CMD="echo"
fi

echo "[1] Générer une clé SSH localement"
echo ""

KEY_FILE="$SSH_DIR/id_horaltscanner"

if [ -f "$KEY_FILE" ]; then
    echo "✓ Clé SSH existe déjà: $KEY_FILE"
else
    echo "Génération d'une nouvelle clé SSH..."
    mkdir -p "$SSH_DIR"
    ssh-keygen -t ed25519 -C "horaltscanner" -f "$KEY_FILE" -N ""
    chmod 600 "$KEY_FILE"
    chmod 644 "$KEY_FILE.pub"
    echo "✓ Clé générée: $KEY_FILE"
fi

echo ""
echo "[2] Copier la clé publique vers le Pi"
echo ""
echo "Votre clé publique SSH:"
echo "---"
cat "$KEY_FILE.pub"
echo "---"
echo ""

read -p "Avez-vous une connexion SSH au Pi? (y/n) " -n 1 -r
echo

if [[ $REPLY =~ ^[Yy]$ ]]; then
    read -p "Entrez l'adresse/hostname du Pi (ex: raspberrypi.local): " PI_HOST
    
    echo ""
    echo "Copie de la clé vers le Pi..."
    ssh-copy-id -i "$KEY_FILE" "pi@$PI_HOST" || {
        echo "Erreur: Impossible de copier la clé"
        echo ""
        echo "Essayez manuellement:"
        echo "1. ssh pi@$PI_HOST"
        echo "2. mkdir -p ~/.ssh"
        echo "3. echo '$(cat $KEY_FILE.pub)' >> ~/.ssh/authorized_keys"
        echo "4. chmod 600 ~/.ssh/authorized_keys"
        exit 1
    }
    
    echo "✓ Clé copiée"
    echo ""
    
    echo "[3] Tester la connexion sans mot de passe"
    echo ""
    ssh -i "$KEY_FILE" "pi@$PI_HOST" 'echo ✓ Connexion SSH réussie' || echo "✗ Erreur connexion"
else
    echo "OK, copiez manuellement la clé publique sur le Pi:"
    echo ""
    echo "Sur votre ordinateur:"
    echo "  cat $KEY_FILE.pub | xclip -selection clipboard"
    echo ""
    echo "Puis sur le Pi:"
    echo "  mkdir -p ~/.ssh"
    echo "  nano ~/.ssh/authorized_keys"
    echo "  # Coller la clé"
    echo "  chmod 600 ~/.ssh/authorized_keys"
fi

echo ""
echo "[4] Configuration ~/.ssh/config (optionnel)"
echo ""

if grep -q "Host horaltscanner" "$SSH_DIR/config" 2>/dev/null; then
    echo "✓ horaltscanner déjà dans ~/.ssh/config"
else
    echo "Ajout de horaltscanner à ~/.ssh/config..."
    mkdir -p "$SSH_DIR"
    cat >> "$SSH_DIR/config" << EOF

Host horaltscanner
    HostName raspberrypi.local
    User pi
    IdentityFile $KEY_FILE
    StrictHostKeyChecking no
    UserKnownHostsFile=/dev/null
EOF
    chmod 600 "$SSH_DIR/config"
    echo "✓ Config ajoutée"
fi

echo ""
echo "Vous pouvez maintenant utiliser:"
echo "  ssh horaltscanner"
echo ""
