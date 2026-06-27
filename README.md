# Gestionnaire de logs de simulation ATC

Webapp de gestion des logs de simulations de contrôle aérien : catalogue,
accès par aéroport et par rôle, remontée de tickets, édition centralisée.

## Lancement

```bash
docker compose up -d --build
```

## Authentification

**Un compte par aéroport.** On se connecte avec le code OACI de l'aéroport
(`LFPG`, `LFBO`…), puis on choisit son rôle pour la session : **pilote** ou
**instructeur**. Un compte `admin` séparé donne accès à tous les centres.


> **Changer les mots de passe :** éditer `data/users.json`, remettre un champ
> `password` en clair, redémarrer le conteneur. Le mot de passe est haché
> automatiquement au démarrage et le champ en clair disparaît.

## Rôles

| Capacité | Pilote | Instructeur | Admin |
|---|:---:|:---:|:---:|
| Déroulé radio | ✔ | ✔ | ✔ |
| Attendus + notes pédago | ✗ | ✔ | ✔ |
| Tickets | ✗ | ✔ | ✔ |
| Édition JSON / tous centres | ✗ | ✗ | ✔ |

Le filtrage pédagogique est appliqué **côté serveur** : un pilote ne reçoit
jamais les attendus, même en inspectant la page.

## Ajouter un aéroport

1. Ajouter le centre dans `data/centres.json`
2. Ajouter le compte dans `data/users.json`
3. Déposer les simulations dans `data/simulations/<CODE>-<NUM>.json`

## Données

Tout est en fichiers JSON dans `data/` (monté en volume Docker). C'est le
seul dossier à sauvegarder.
