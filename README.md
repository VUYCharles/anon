# Gestionnaire de logs de simulation ATC

Webapp de gestion des logs de simulations de contrôle aérien : catalogue,
accès par aéroport et par rôle, remontée de tickets, édition centralisée.


## Organisation par stage

Les logs de simulation sont rangés par **stage** (module de formation) : un
sous-dossier de `data/simulations/` = un stage. Le nom du stage suit aussi le
champ `logsim.categorie` du fichier.

```
data/simulations/
├── ARMAGEDDON/   # 195ARMA_SIM, ARMA_SIMA, BOB1…
├── BO_ITM/       # ARMA, ARMA44, ARMATESTBOB
├── FSAU/         # AWAE14L1F, FSAU14_1…
├── ITM/          # ITM14M2PC
├── PC2/          # APPITM14L11PC_DAL
└── *.simlog      # simulations sans stage (rangées à la racine)
```

L'accueil affiche le **mur des stages** ; chaque carte ouvre le **contenu du
stage** (ses simulations, avec marqueur jour/nuit). L'isolation par centre et le
filtrage par rôle restent inchangés.


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
| Édition `.simlog` / tous centres | ✗ | ✗ | ✔ |

Le filtrage pédagogique est appliqué **côté serveur** : un pilote ne reçoit
jamais les attendus, même en inspectant la page.

## Ajouter un aéroport

1. Ajouter le centre dans `data/centres.json`
2. Ajouter le compte dans `data/users.json`
3. Déposer les logs de simulation dans `data/simulations/<id>.simlog`

## Données

Tout est en fichiers dans `data/` (monté en volume Docker), seul dossier à
sauvegarder. Les comptes, centres, tickets et journal d'audit restent en `.json` ;
les **logs de simulation sont au format `.simlog`** dans `data/simulations/`.

### Format `.simlog`

Un `.simlog` est un fichier JSON au schéma natif du simulateur :

- `instructor_log` : notes instructeur (objet, souvent vide) ;
- `pilot_logs` : liste de positions pseudo-pilotes `{ role, events[] }`, chaque
  événement étant `{ callsign, description, time }` ;
- `properties` : métadonnées du scénario (`name`, `description`, `duration`,
  `start_date`, `update_date`, `weather`, `flightCount`…).

À cela s'ajoute une **enveloppe applicative `logsim`** propre à Simlog, qui
porte ce dont l'application a besoin et qui n'existe pas dans le schéma natif :
`id`, `centre` (cloisonnement), `terrain`, `position`, `difficulte`, `version`,
`categorie`, et — pour les logs pédagogiques convertis depuis l'ancien format
`.json` — la timeline pédagogique complète (`evenements` avec `attendu` /
`note_pedago`) et les `attendus_pedagogiques`.

À l'affichage, une couche de normalisation reconstruit une timeline commune :
soit depuis `logsim.evenements` (logs pédagogiques), soit en fusionnant et triant
chronologiquement les `pilot_logs` (logs natifs).
