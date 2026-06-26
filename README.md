# ATC Log Manager — Gestionnaire de logs de simulation de contrôle aérien

Prototype fonctionnel d'une webapp de gestion des logs de simulations
de contrôle aérien. La **visualisation** des logs existe déjà côté simulateurs ;
cette application est le **gestionnaire** : catalogue, accès par profil, remontée
de tickets et édition centralisée.

---

## Lancement rapide

### Avec Docker (recommandé)

```bash
docker compose up --build
```

Puis ouvrir http://localhost:5000

### Sans Docker (développement)

```bash
pip install -r requirements.txt
python app.py
```

### Comptes de démonstration

Tous les comptes ont le mot de passe `demo` (cliquables sur la page de connexion).

| Identifiant       | Profil      | Centre |
|-------------------|-------------|--------|
| `pilote_cdg`      | pilote      | LFPG   |
| `instructeur_cdg` | instructeur | LFPG   |
| `pilote_tls`      | pilote      | LFBO   |
| `instructeur_tls` | instructeur | LFBO   |
| `admin`           | admin       | (tous) |

---

## Les 3 profils et leurs droits

| Capacité                                   | Pilote | Instructeur | Admin |
|--------------------------------------------|:------:|:-----------:|:-----:|
| Voir les simulations de son centre         |   ✔    |      ✔      |   ✔   |
| Voir les simulations des autres centres    |   ✗    |      ✗      |   ✔   |
| Voir le déroulé (journal radio)            |   ✔    |      ✔      |   ✔   |
| Voir les attendus pédagogiques             |   ✗    |      ✔      |   ✔   |
| Voir les notes pédagogiques par événement  |   ✗    |      ✔      |   ✔   |
| Remonter des tickets                       |   ✗    |      ✔      |   ✔   |
| Commenter les tickets                      |   ✗    |      ✔      |   ✔   |
| Changer le statut d'un ticket              |   ✗    |      ✗      |   ✔   |
| Éditer le JSON d'une simulation            |   ✗    |      ✗      |   ✔   |

> **Isolation par centre** : un pilote ou un instructeur ne voit *que* les
> simulations de son terrain. C'est appliqué **côté serveur** — les attendus
> pédagogiques ne sont jamais envoyés au navigateur d'un pilote, même en
> inspectant le code source de la page.

---

## Format JSON d'une simulation

Chaque simulation est un fichier dans `data/simulations/<ID>.json`.

```jsonc
{
  "id": "LFPG-001",
  "titre": "Départ en heure de pointe — piste 27R",
  "centre": "LFPG",                // sert à l'isolation
  "terrain": "LFPG",
  "position": "Tour (TWR)",
  "version": 1,                    // incrémentée à chaque édition admin
  "difficulte": "Intermédiaire",
  "duree_estimee_min": 12,
  "meteo": "CAVOK, vent 250/08kt, QNH 1018",
  "attendus_pedagogiques": [       // INSTRUCTEUR/ADMIN uniquement
    "Établir et tenir une séquence de départ..."
  ],
  "evenements": [
    {
      "t": "12:02:02",            // horodatage
      "acteur": "F-BVUH",         // avion, "Élève contrôleur", centre mitoyen...
      "type": "avion_message",    // voir types ci-dessous
      "frequence": "TWR 119.250", // ou null
      "contenu": "Tour, F-BVUH, prêt au départ.",
      "attendu": null,            // INSTRUCTEUR/ADMIN : ce que l'élève doit faire
      "note_pedago": null         // INSTRUCTEUR/ADMIN : note de l'instructeur
    }
  ]
}
```

### Types d'événements

| Type                 | Sens                                          |
|----------------------|-----------------------------------------------|
| `avion_message`      | Message radio d'un avion en fréquence         |
| `avion_action`       | Action physique (décolle, roule, atterrit)    |
| `eleve_instruction`  | Instruction attendue de l'élève contrôleur    |
| `telephone_sortant`  | Appel téléphonique vers un centre mitoyen     |
| `telephone_entrant`  | Appel téléphonique reçu d'un centre mitoyen   |
| `ambiance`           | Élément de contexte (météo, trafic)           |

Les champs `attendu` et `note_pedago`, ainsi que `attendus_pedagogiques`, sont
**filtrés côté serveur** pour le profil pilote.

---

## Architecture

```
Navigateur ──HTTP──> Flask (app.py) ──> fichiers JSON (data/)
                       │
                       ├─ sessions + rôles (auth)
                       ├─ isolation par centre
                       └─ filtrage des données par profil
```

- **Backend** : Flask, sessions, mots de passe hachés (Werkzeug).
- **Stockage** : fichiers JSON (pas de base de données). Volume Docker pour la
  persistance.
- **Frontend** : HTML/CSS classiques, polices système (fonctionne hors-ligne).

### Structure du projet

```
atc-log-manager/
├── app.py                  # backend + contrôle d'accès
├── data/
│   ├── centres.json
│   ├── users.json          # mots de passe hachés au 1er démarrage
│   ├── tickets.json
│   ├── audit.json
│   └── simulations/*.json  # les logs
├── templates/              # vues Jinja
├── static/style.css
├── Dockerfile
└── docker-compose.yml
```

---

## Ce qui est fait / ce qui reste

**Fait dans ce prototype :** authentification 3 profils, isolation par centre,
catalogue, journal radio filtré, attendus pédagogiques, workflow ticket complet
(3 types, discussion, statuts), édition JSON admin versionnée, journal d'audit.

**À prévoir pour la production :** connexion au vrai serveur de JSON externe
(ici les fichiers sont locaux), SSO / annuaire, base de données si le volume
l'exige, import automatisé depuis les simulateurs, tests de charge, statistiques.

---

## Gestion des comptes

Pour ajouter un utilisateur, éditer `data/users.json` en ajoutant un champ
`password` en clair — il sera haché automatiquement au prochain démarrage :

```json
"instructeur_nce": {
  "nom": "Paul Riviere",
  "role": "instructeur",
  "centre": "LFMN",
  "password": "monmotdepasse"
}
```
