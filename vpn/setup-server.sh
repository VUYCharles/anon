#!/usr/bin/env bash
# Installe et configure le serveur WireGuard sur le VPS.
# À lancer UNE SEULE FOIS, avec sudo : sudo ./setup-server.sh
set -euo pipefail

if [ "$EUID" -ne 0 ]; then echo "À lancer avec sudo."; exit 1; fi

WG_DIR=/etc/wireguard
SERVER_IP=10.8.0.1
SUBNET=10.8.0.0/24
WG_PORT=51820
APP_PORT=8080          # port public de l'app (celui exposé par docker-compose)

echo "→ Installation de WireGuard…"
apt-get update -qq
apt-get install -y wireguard qrencode

echo "→ Génération des clés serveur…"
cd "$WG_DIR"
umask 077
if [ ! -f server.key ]; then
  wg genkey | tee server.key | wg pubkey > server.pub
fi

echo "→ Écriture de wg0.conf…"
cat > wg0.conf <<CONF
[Interface]
Address = ${SERVER_IP}/24
ListenPort = ${WG_PORT}
PrivateKey = $(cat server.key)
CONF

echo "→ Activation du service…"
systemctl enable wg-quick@wg0
systemctl restart wg-quick@wg0

echo "→ Configuration du pare-feu…"
ufw allow ${WG_PORT}/udp
# L'app n'est plus joignable publiquement : seulement via le VPN.
ufw delete allow ${APP_PORT} 2>/dev/null || true
ufw allow from ${SUBNET} to any port ${APP_PORT}

echo
echo "✅ Serveur WireGuard prêt."
echo "   L'app n'est désormais accessible QUE via le VPN, à : http://${SERVER_IP}:${APP_PORT}"
echo "   Ajoutez un client avec : sudo ./add-client.sh <nom>"
