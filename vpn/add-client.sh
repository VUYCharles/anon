#!/usr/bin/env bash
# Ajoute un client VPN et génère sa config.
# Usage : sudo ./add-client.sh lfpg
set -euo pipefail

if [ "$EUID" -ne 0 ]; then echo "À lancer avec sudo."; exit 1; fi

NAME="${1:-}"
if [ -z "$NAME" ]; then
  echo "Usage : sudo ./add-client.sh <nom>   (ex : lfpg, lfbo, instructeur-nce)"
  exit 1
fi

WG_DIR=/etc/wireguard
ENDPOINT_IP=152.228.137.216   # IP publique du VPS
WG_PORT=51820
PREFIX=10.8.0
cd "$WG_DIR"
umask 077

# Prochaine IP libre (les clients commencent à .2, le serveur est .1)
LAST=$(grep -oP "AllowedIPs = ${PREFIX}\.\K[0-9]+" wg0.conf 2>/dev/null | sort -n | tail -1 || true)
NEXT=$(( ${LAST:-1} + 1 ))
CLIENT_IP="${PREFIX}.${NEXT}"

echo "→ Génération des clés pour « ${NAME} » (IP ${CLIENT_IP})…"
wg genkey | tee "client-${NAME}.key" | wg pubkey > "client-${NAME}.pub"
CLIENT_PRIV=$(cat "client-${NAME}.key")
CLIENT_PUB=$(cat "client-${NAME}.pub")
SERVER_PUB=$(cat server.pub)

# Ajout du peer côté serveur
cat >> wg0.conf <<CONF

[Peer]
# ${NAME}
PublicKey = ${CLIENT_PUB}
AllowedIPs = ${CLIENT_IP}/32
CONF

# Rechargement à chaud (ne coupe pas les tunnels existants)
wg syncconf wg0 <(wg-quick strip wg0)

# Fichier de config à remettre au client
OUT="client-${NAME}.conf"
cat > "$OUT" <<CONF
[Interface]
PrivateKey = ${CLIENT_PRIV}
Address = ${CLIENT_IP}/32

[Peer]
PublicKey = ${SERVER_PUB}
Endpoint = ${ENDPOINT_IP}:${WG_PORT}
AllowedIPs = 10.8.0.0/24
PersistentKeepalive = 25
CONF

echo
echo "✅ Client « ${NAME} » ajouté."
echo "   Fichier de config : ${WG_DIR}/${OUT}"
echo "   → à transmettre de façon sécurisée à l'utilisateur."
echo
echo "   QR code (pour l'app mobile WireGuard) :"
qrencode -t ansiutf8 < "$OUT"
