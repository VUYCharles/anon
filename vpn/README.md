# VPN WireGuard — Simlog

Le VPN rend l'application **invisible depuis internet** : le port 8080 n'est
plus joignable directement, uniquement via le tunnel chiffré. Seuls les postes
disposant d'une config WireGuard peuvent atteindre l'app.

Une fois le VPN actif, l'app n'est plus sur `http://152.228.137.216:8080`
mais sur **`http://10.8.0.1:8080`** (accessible seulement quand le VPN est connecté).

---

## Installation (une seule fois, sur le VPS)

```bash
cd /opt/anon/vpn
sudo ./setup-server.sh
```

Ce script installe WireGuard, génère les clés du serveur, ouvre le port VPN
(51820/udp) et restreint le port 8080 au réseau VPN.

---

## Ajouter un utilisateur (un par aéroport / personne)

```bash
cd /opt/anon/vpn
sudo ./add-client.sh lfpg
```

Le script :
- attribue une IP libre (10.8.0.2, .3, …),
- ajoute le client au serveur à chaud (sans couper les autres),
- génère un fichier `client-lfpg.conf` **et** un QR code.

Remettre le fichier `.conf` (ou le QR code) à l'utilisateur **de façon
sécurisée** (il contient sa clé privée — jamais par email en clair).

---

## Côté utilisateur

1. Installer l'app **WireGuard** (gratuite) :
   - Windows / macOS / Linux : https://www.wireguard.com/install/
   - Android / iOS : sur le store, app officielle « WireGuard ».
2. Importer la config :
   - **Ordinateur** : « Import tunnel from file » → choisir le `.conf`.
   - **Mobile** : « + » → scanner le QR code.
3. Activer le tunnel (bouton on/off).
4. Ouvrir `http://10.8.0.1:8080` dans le navigateur.

Quand l'utilisateur a fini, il désactive le tunnel. Tant qu'il n'est pas
connecté au VPN, l'app lui est inaccessible.

---

## Maintenance

| Action | Commande (sur le VPS, en sudo) |
|---|---|
| État du VPN et clients connectés | `sudo wg show` |
| Redémarrer le VPN | `sudo systemctl restart wg-quick@wg0` |
| Voir la config serveur | `sudo cat /etc/wireguard/wg0.conf` |
| Lister les clients | `grep '#' /etc/wireguard/wg0.conf` |

### Révoquer un accès

Éditer la config serveur et supprimer le bloc `[Peer]` de l'utilisateur :

```bash
sudo nano /etc/wireguard/wg0.conf
```

Supprimer les 4 lignes du peer concerné (`[Peer]`, `# nom`, `PublicKey`,
`AllowedIPs`), puis recharger sans couper les autres :

```bash
sudo wg syncconf wg0 <(sudo wg-quick strip wg0)
```

### Sauvegarde

Le dossier `/etc/wireguard/` contient toutes les clés et configs. Le
sauvegarder permet de tout restaurer :

```bash
sudo tar czf ~/wireguard-backup.tar.gz /etc/wireguard
```

> ⚠️ Ce dossier contient les clés privées : le garder hors de Git et hors de
> tout stockage public.

---

## Dépannage

**« Le tunnel se connecte mais l'app ne répond pas »**
Vérifier que le conteneur tourne (`docker compose ps`) et que l'URL est bien
`http://10.8.0.1:8080` (pas l'IP publique).

**« Handshake did not complete »**
Le port 51820/udp n'est pas ouvert, ou l'IP du VPS (`Endpoint`) a changé.
Vérifier `sudo ufw status` et l'IP dans le `.conf` client.

**« L'app reste accessible publiquement »**
Le pare-feu n'a pas été appliqué. Relancer :
```bash
sudo ufw delete allow 8080
sudo ufw allow from 10.8.0.0/24 to any port 8080
```
