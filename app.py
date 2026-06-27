"""
Gestionnaire de logs de simulation ATC
Backend Flask — stockage des logs de simulation au format .simlog, authentification
par session, isolation stricte par centre et filtrage des données selon le profil.

Les logs de simulation sont stockés au format .simlog (schéma natif
instructor_log / pilot_logs / properties), complété par une enveloppe applicative
"logsim" (centre, id, version, contenu pédagogique éventuel). Une couche de
normalisation reconstruit un modèle de rendu commun pour les vues et templates.

Code by @VUYCharles
"""
import os
import json
import glob
from datetime import datetime
from functools import wraps
from threading import Lock

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, abort, jsonify
)
from werkzeug.security import generate_password_hash, check_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
SIM_DIR = os.path.join(DATA_DIR, "simulations")

# Extension des logs de simulation (remplace l'ancien .json)
SIM_EXT = ".simlog"

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-a-changer-en-production")

_write_lock = Lock()


# ---------------------------------------------------------------------------
# Accès aux données (couche fichiers JSON)
# ---------------------------------------------------------------------------
def _load(path, default=None):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default if default is not None else {}


def _save(path, data):
    with _write_lock:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)


def load_centres():
    return _load(os.path.join(DATA_DIR, "centres.json"), {})

def load_users():
    return _load(os.path.join(DATA_DIR, "users.json"), {})

def save_users(users):
    _save(os.path.join(DATA_DIR, "users.json"), users)

def load_tickets():
    return _load(os.path.join(DATA_DIR, "tickets.json"), {})

def save_tickets(tickets):
    _save(os.path.join(DATA_DIR, "tickets.json"), tickets)

def load_audit():
    return _load(os.path.join(DATA_DIR, "audit.json"), [])

def save_audit(audit):
    _save(os.path.join(DATA_DIR, "audit.json"), audit)

def _iter_sim_paths():
    """Parcourt récursivement data/simulations/ (un sous-dossier = un stage)."""
    for root, _dirs, files in os.walk(SIM_DIR):
        for fname in files:
            if fname.endswith(SIM_EXT) and ".bak" not in fname:
                yield os.path.join(root, fname)


def _sim_path(sim_id):
    """Résout le chemin d'un .simlog par son identifiant, où qu'il soit rangé."""
    for path in _iter_sim_paths():
        if os.path.splitext(os.path.basename(path))[0] == sim_id:
            return path
    return None


def _stage_from_path(path):
    """Nom de stage déduit du sous-dossier (None si le fichier est à la racine)."""
    rel = os.path.relpath(os.path.dirname(path), SIM_DIR)
    if rel in (".", ""):
        return None
    return rel.split(os.sep)[0].replace("_", " ")


def load_simulation(sim_id):
    """Charge un .simlog et renvoie le modèle de rendu normalisé."""
    path = _sim_path(sim_id)
    if path is None:
        return None
    raw = _load(path)
    if raw is None:
        return None
    return normalize_simulation(raw, sim_id, _stage_from_path(path))


def load_simulation_raw(sim_id):
    """Charge le contenu brut du fichier .simlog (schéma natif + enveloppe)."""
    path = _sim_path(sim_id)
    if path is None or not os.path.exists(path):
        return None
    return _load(path)


def save_simulation_raw(sim_id, data):
    """Réécrit le .simlog à son emplacement existant (ou à la racine si nouveau)."""
    path = _sim_path(sim_id) or os.path.join(SIM_DIR, f"{sim_id}{SIM_EXT}")
    _save(path, data)


def list_simulations():
    """Liste les simulations sous forme de modèles normalisés."""
    sims = []
    for path in sorted(_iter_sim_paths(), key=lambda p: os.path.basename(p).lower()):
        raw = _load(path)
        if raw:
            sim_id = os.path.splitext(os.path.basename(path))[0]
            sims.append(normalize_simulation(raw, sim_id, _stage_from_path(path)))
    return sims


def group_by_stage(sims):
    """Regroupe une liste de simulations par stage, stages triés alphabétiquement.
    Renvoie (stages, sans_stage) où stages = [(nom, [sims]), ...]."""
    stages, sans_stage = {}, []
    for s in sims:
        if s.get("stage"):
            stages.setdefault(s["stage"], []).append(s)
        else:
            sans_stage.append(s)
    ordered = [(nom, stages[nom]) for nom in sorted(stages, key=str.lower)]
    return ordered, sans_stage


# ---------------------------------------------------------------------------
# Normalisation .simlog -> modèle de rendu commun
# ---------------------------------------------------------------------------
def _time_key(t):
    """Clé de tri à partir d'une heure 'HH:MM' ou 'HH:MM:SS'."""
    try:
        parts = [int(p) for p in (t or "").split(":")]
        while len(parts) < 3:
            parts.append(0)
        return (0, parts[0], parts[1], parts[2])
    except (ValueError, AttributeError):
        return (1, 0, 0, 0)  # heures invalides en fin de liste


# ---------------------------------------------------------------------------
# Nettoyage / structuration des descriptions natives .simlog
#
# Les descriptions natives sont des blocs bruts saisis à la main, du type :
#   "LFCK LFPO  *appel ' mise en route CLG8102'  (19)"
#   "LFMK GMTT TO 56 (si changement de SID : AT PRC MASAM3E)"
#   "LFBF LFBT *TEL LFBF appel AW 'mise en route' (1415TO)"
# On en extrait des champs propres (route, message radio, n° de strip, heure de
# décollage…) pour un rendu lisible, sans guillemets ni parenthèses orphelines
# ni heures qui se répètent.
# ---------------------------------------------------------------------------
import re as _re

_ELISION = _re.compile(r"\b([ldnjmstcLDNJMSTC]|qu|Qu|jusqu|lorsqu|puisqu)'", _re.I)
_SCENARIO = _re.compile(
    r"\s*((?:ALERTE[^']*?BOMBE|COLLISION AVIAIRE|GIVRAGE FORT|PANNE [A-ZÉÈ]+|MENACE[^']*))"
)
_ROUTE = _re.compile(r"\s*([A-Z]{4})\s+([A-Z]{4})\b")
_TKOFF_TIME = _re.compile(r"\b(\d{2})(\d{2})\s*TO\b")
_TKOFF_EVT = _re.compile(r"\bTO\s+(\d{1,3})\b")
_STRIP = _re.compile(r"\((\d{1,3})\)")


def _clean_text(s):
    """Normalise espaces, supprime guillemets/parenthèses orphelins et vides."""
    if not s:
        return ""
    s = s.replace("''", "'").replace('"', "'")
    s = _re.sub(r"\(\s+", "(", s)
    s = _re.sub(r"\s+\)", ")", s)
    s = _re.sub(r"\(\s*\)", "", s)           # parenthèses vides
    s = _re.sub(r"\s{2,}", " ", s)
    return s.strip(" '\u00a0\t").strip()


def _extract_quotes(s):
    """Extrait les messages entre guillemets simples, en protégeant les
    apostrophes d'élision françaises (l', d', qu'…)."""
    sent = "\u0001"
    prot = _ELISION.sub(lambda m: m.group(1) + sent, s)
    msgs = []

    def repl(m):
        inner = _clean_text(m.group(1).replace(sent, "'"))
        if inner:
            msgs.append(inner)
        return " "

    out = _re.sub(r"'([^']*)'", repl, prot).replace(sent, "'")
    return msgs, out


def parse_native_description(desc):
    """Transforme une description native brute en champs structurés et propres."""
    raw = desc or ""
    work = " " + raw.strip().lstrip("*").strip() + " "
    work = work.replace("''", "'")

    res = {
        "origine": None, "destination": None,
        "decollage": None, "strip": None,
        "scenario": None, "consigne": None,
        "message": None, "type": "avion_message",
    }

    # Scénario en préfixe (alerte à la bombe, collision aviaire, panne…)
    scen = _SCENARIO.match(work)
    if scen:
        res["scenario"] = _clean_text(scen.group(1))
        work = work[scen.end():]

    # Route OACI en tête : LFCK LFPO
    rm = _ROUTE.match(work)
    if rm:
        res["origine"], res["destination"] = rm.group(1), rm.group(2)
        work = work[rm.end():]

    # Heure de décollage embarquée : 1415TO -> 14:15 (évite la répétition d'heure)
    tm = _TKOFF_TIME.search(work)
    if tm:
        hh, mm = int(tm.group(1)), int(tm.group(2))
        if hh <= 23 and mm <= 59:
            res["decollage"] = f"{hh:02d}:{mm:02d}"
            work = work[:tm.start()] + " " + work[tm.end():]

    # Événement décollage : TO 19 (le nombre = n° de strip)
    is_takeoff = False
    to_evt = _TKOFF_EVT.search(work)
    if to_evt:
        res["strip"] = to_evt.group(1)
        is_takeoff = True
        work = work[:to_evt.start()] + " " + work[to_evt.end():]

    # Numéro de strip en fin : (19)
    sm = _STRIP.search(work)
    if sm:
        res["strip"] = sm.group(1)
        work = work[:sm.start()] + " " + work[sm.end():]

    # Messages entre guillemets
    msgs, work = _extract_quotes(work)
    if msgs:
        res["message"] = " / ".join(msgs)

    # Type d'événement (pilote la couleur)
    u = raw.upper()
    if res["scenario"] or any(k in u for k in ("ALERTE", "BOMBE", "MENACE", "COLLISION")):
        res["type"] = "ambiance"
    elif "*RADIO" in u or _re.search(r"\bRADIO\b", u):
        res["type"] = "avion_message"
    elif "*TEL" in u or "*APPEL" in u or _re.search(r"\bAPPEL\b", u) or "*TÉL" in u:
        res["type"] = "telephone_entrant"
    elif any(k in u for k in ("PANNE", "GIVR", "LARGU", "PARA")):
        res["type"] = "avion_action"
    elif is_takeoff:
        res["type"] = "avion_action"

    # Consigne = reste nettoyé des marqueurs *appel/*radio/*tel
    leftover = _clean_text(work)
    leftover = _re.sub(r"\*\s*(appel|radio|tel|tél)\b", "", leftover, flags=_re.I)
    leftover = _re.sub(r"^\s*(appel|radio|tel|mise en route)\b", "", leftover, flags=_re.I)
    leftover = _clean_text(leftover.strip(" :*-/'\u00a0"))
    if is_takeoff:
        leftover = "Décollage" if not leftover else "Décollage — " + leftover
    res["consigne"] = leftover or None

    return res


def _timeline_from_pilot_logs(raw):
    """Construit une timeline chronologique unifiée et nettoyée à partir des
    pilot_logs natifs."""
    evenements = []
    for log in raw.get("pilot_logs", []):
        role = log.get("role", "")
        for ev in log.get("events", []):
            desc = ev.get("description", "")
            p = parse_native_description(desc)
            # contenu = repli lisible (vue pilote / templates anciens)
            contenu = p["message"] or p["consigne"] or p["scenario"] or _clean_text(desc)
            evenements.append({
                "t": ev.get("time", ""),
                "acteur": ev.get("callsign", ""),
                "role": role,
                "type": p["type"],
                "frequence": None,
                "origine": p["origine"],
                "destination": p["destination"],
                "decollage": p["decollage"],
                "strip": p["strip"],
                "scenario": p["scenario"],
                "consigne": p["consigne"],
                "message": p["message"],
                "contenu": contenu,
                "source": _clean_text(desc),
                "attendu": None,
                "note_pedago": None,
            })
    evenements.sort(key=lambda e: _time_key(e["t"]))
    return evenements


def _periode_from_start(start_date):
    """'jour' / 'nuit' à partir de l'heure de début (nuit : avant 7h ou après 21h)."""
    try:
        hh = int(str(start_date)[11:13])
    except (ValueError, TypeError):
        return None
    return "nuit" if (hh < 7 or hh >= 21) else "jour"


def normalize_simulation(raw, sim_id, stage=None):
    """
    Reconstruit un modèle de rendu commun, que la simulation soit un .simlog natif
    (LFBO) ou un .simlog issu d'un ancien log pédagogique converti.
    `stage` est déduit du sous-dossier ; à défaut on retombe sur logsim.categorie.
    """
    env = raw.get("logsim", {}) or {}
    props = raw.get("properties", {}) or {}

    model = {
        "id": env.get("id", sim_id),
        "titre": props.get("name") or env.get("id") or sim_id,
        "soustitre": (props.get("description") or "").splitlines()[0].strip() if props.get("description") else "",
        "centre": env.get("centre"),
        "terrain": env.get("terrain") or env.get("centre"),
        "position": env.get("position") or "—",
        "version": env.get("version", 1),
        "date_creation": env.get("date_creation") or props.get("start_date"),
        "date_modification": env.get("date_modification") or props.get("update_date"),
        "duree_estimee_min": props.get("duration") or 0,
        "difficulte": env.get("difficulte") or "Non précisé",
        "meteo": props.get("weather") or "",
        "description": props.get("description") or "",
        "objectives": props.get("objectives") or "",
        "flight_count": props.get("flightCount"),
        "categorie": env.get("categorie"),
        "stage": stage or env.get("categorie"),
        "periode": _periode_from_start(props.get("start_date")),
        "instructor_log": raw.get("instructor_log") or {},
        "attendus_pedagogiques": [],
        "evenements": [],
    }

    if env.get("evenements") is not None:
        # Log pédagogique converti : on conserve la timeline d'origine (riche)
        for ev in env["evenements"]:
            ev = dict(ev)
            ev.setdefault("role", None)
            model["evenements"].append(ev)
        model["attendus_pedagogiques"] = env.get("attendus_pedagogiques", [])
    else:
        # .simlog natif : timeline reconstruite depuis les pilot_logs
        model["evenements"] = _timeline_from_pilot_logs(raw)
        model["attendus_pedagogiques"] = [
            l.strip() for l in (props.get("objectives") or "").splitlines() if l.strip()
        ]

    return model


# ---------------------------------------------------------------------------
# Hachage des mots de passe au démarrage
# ---------------------------------------------------------------------------
def hash_seed_passwords():
    users = load_users()
    changed = False
    for username, u in users.items():
        if "password" in u and "password_hash" not in u:
            u["password_hash"] = generate_password_hash(u.pop("password"))
            changed = True
    if changed:
        save_users(users)

hash_seed_passwords()


# ---------------------------------------------------------------------------
# Authentification et contrôle d'accès
# ---------------------------------------------------------------------------
def current_user():
    """
    Nouveau système : un compte par aéroport.
    La session stocke 'centre' (code OACI) et 'role' (pilote/instructeur/admin).
    Le rôle est choisi après la connexion via /choisir-role.
    """
    role = session.get("role")
    if not role:
        return None
    if role == "admin":
        return {"username": "admin", "nom": "Administration", "role": "admin", "centre": None}
    centre = session.get("centre")
    if not centre:
        return None
    centres = load_centres()
    nom = centres.get(centre, {}).get("nom", centre)
    return {"username": centre, "nom": nom, "role": role, "centre": centre}


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        role = session.get("role")
        if not role:
            # Connecté à un aéroport mais rôle pas encore choisi
            if session.get("centre"):
                return redirect(url_for("choisir_role"))
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def role_required(*roles):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            user = current_user()
            if not user:
                return redirect(url_for("login", next=request.path))
            if user["role"] not in roles:
                abort(403)
            return view(*args, **kwargs)
        return wrapped
    return decorator


def can_access_simulation(user, sim):
    if user["role"] == "admin":
        return True
    return sim.get("centre") == user.get("centre")


def filter_simulation_for_role(sim, role):
    if role in ("instructeur", "admin"):
        return sim
    clean = dict(sim)
    clean.pop("attendus_pedagogiques", None)
    # Briefing et notes instructeur masqués aux pilotes
    clean["description"] = ""
    clean["objectives"] = ""
    clean["instructor_log"] = {}
    clean["evenements"] = []
    for ev in sim.get("evenements", []):
        ev_clean = dict(ev)
        ev_clean.pop("note_pedago", None)
        ev_clean.pop("attendu", None)
        clean["evenements"].append(ev_clean)
    return clean


@app.context_processor
def inject_globals():
    return {
        "current_user": current_user(),
        "centres": load_centres(),
    }


TYPE_LABELS = {
    "avion_message": "Message avion",
    "avion_action": "Action avion",
    "eleve_instruction": "Instruction élève",
    "telephone_sortant": "Appel téléphonique sortant",
    "telephone_entrant": "Appel téléphonique entrant",
    "ambiance": "Ambiance",
}
TICKET_TYPE_LABELS = {
    "signalement": "Signalement",
    "modification": "Proposition de modification",
    "pedagogique": "Point pédagogique",
}
STATUT_LABELS = {
    "ouvert": "Ouvert",
    "en_cours": "En cours",
    "resolu": "Résolu",
    "rejete": "Rejeté",
}

app.jinja_env.globals["TYPE_LABELS"] = TYPE_LABELS
app.jinja_env.globals["TICKET_TYPE_LABELS"] = TICKET_TYPE_LABELS
app.jinja_env.globals["STATUT_LABELS"] = STATUT_LABELS


# ---------------------------------------------------------------------------
# Routes : authentification
# ---------------------------------------------------------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user():
        return redirect(url_for("index"))
    if request.method == "POST":
        identifier = request.form.get("username", "").strip().upper()
        if identifier == "ADMIN":
            identifier = "admin"
        password = request.form.get("password", "")
        users = load_users()
        u = users.get(identifier)
        if u and check_password_hash(u.get("password_hash", ""), password):
            if u.get("role") == "admin":
                # Admin : rôle déjà connu, on va directement à l'app
                session.clear()
                session["role"] = "admin"
                session["centre"] = None
                return redirect(url_for("index"))
            else:
                # Aéroport : rôle à choisir
                session.clear()
                session["centre"] = identifier
                return redirect(url_for("choisir_role"))
        flash("Code aéroport ou mot de passe incorrect.", "error")
    return render_template("login.html", users=load_users(), centres=load_centres())


@app.route("/choisir-role", methods=["GET", "POST"])
def choisir_role():
    if not session.get("centre"):
        return redirect(url_for("login"))
    if session.get("role"):
        return redirect(url_for("index"))
    if request.method == "POST":
        role = request.form.get("role")
        if role in ("pilote", "instructeur"):
            session["role"] = role
            return redirect(url_for("index"))
    centres = load_centres()
    centre_nom = centres.get(session["centre"], {}).get("nom", session["centre"])
    return render_template("choisir_role.html", centre_nom=centre_nom, centre_code=session["centre"])


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ---------------------------------------------------------------------------
# Routes : liste des simulations
# ---------------------------------------------------------------------------
@app.route("/")
@login_required
def index():
    user = current_user()
    sims = [s for s in list_simulations() if can_access_simulation(user, s)]
    open_counts = _open_ticket_counts()
    stages, sans_stage = group_by_stage(sims)
    return render_template(
        "simulations.html",
        stages=stages,
        sans_stage=sans_stage,
        total=len(sims),
        open_counts=open_counts,
    )


@app.route("/stage/<stage>")
@login_required
def stage_detail(stage):
    user = current_user()
    sims = [
        s for s in list_simulations()
        if can_access_simulation(user, s) and (s.get("stage") or "") == stage
    ]
    if not sims:
        abort(404)
    sims.sort(key=lambda s: str(s["id"]).lower())
    open_counts = _open_ticket_counts()
    return render_template(
        "stage.html",
        stage=stage,
        simulations=sims,
        open_counts=open_counts,
    )


def _open_ticket_counts():
    counts = {}
    for t in load_tickets().values():
        if t["statut"] in ("ouvert", "en_cours"):
            counts[t["simulation_id"]] = counts.get(t["simulation_id"], 0) + 1
    return counts


# ---------------------------------------------------------------------------
# Routes : vue déroulé d'une simulation
# ---------------------------------------------------------------------------
@app.route("/simulation/<sim_id>")
@login_required
def simulation(sim_id):
    user = current_user()
    sim = load_simulation(sim_id)
    if not sim:
        abort(404)
    if not can_access_simulation(user, sim):
        abort(403)
    filtered = filter_simulation_for_role(sim, user["role"])
    sim_tickets = {}
    if user["role"] in ("instructeur", "admin"):
        for t in load_tickets().values():
            if t["simulation_id"] == sim_id:
                sim_tickets.setdefault(t["event_index"], []).append(t)
    return render_template("simulation.html", sim=filtered, sim_tickets=sim_tickets)


# ---------------------------------------------------------------------------
# Routes : tickets
# ---------------------------------------------------------------------------
@app.route("/ticket/nouveau", methods=["POST"])
@role_required("instructeur", "admin")
def ticket_nouveau():
    user = current_user()
    sim_id = request.form.get("simulation_id")
    sim = load_simulation(sim_id)
    if not sim or not can_access_simulation(user, sim):
        abort(403)

    tickets = load_tickets()
    new_id = f"TKT-{len(tickets) + 1:03d}"
    while new_id in tickets:
        new_id = f"TKT-{int(new_id.split('-')[1]) + 1:03d}"

    ticket = {
        "id": new_id,
        "simulation_id": sim_id,
        "event_index": int(request.form.get("event_index", -1)),
        "type": request.form.get("type", "signalement"),
        "titre": request.form.get("titre", "").strip() or "(sans titre)",
        "statut": "ouvert",
        "auteur": user["username"],
        "auteur_nom": f"{user['nom']} ({user['role']})",
        "centre": sim.get("centre"),
        "date": datetime.now().isoformat(timespec="seconds"),
        "contenu": request.form.get("contenu", "").strip(),
        "avant": request.form.get("avant", "").strip() or None,
        "apres": request.form.get("apres", "").strip() or None,
        "commentaires": [],
        "resolution": None,
    }
    tickets[new_id] = ticket
    save_tickets(tickets)
    flash(f"Ticket {new_id} créé.", "success")
    return redirect(url_for("simulation", sim_id=sim_id) + f"#ev-{ticket['event_index']}")


@app.route("/tickets")
@login_required
def tickets_list():
    user = current_user()
    if user["role"] == "pilote":
        abort(403)
    all_tickets = load_tickets()
    if user["role"] == "admin":
        visible = list(all_tickets.values())
    else:
        visible = [t for t in all_tickets.values() if t["centre"] == user["centre"]]
    statut_filter = request.args.get("statut")
    if statut_filter:
        visible = [t for t in visible if t["statut"] == statut_filter]
    visible.sort(key=lambda t: t["date"], reverse=True)
    return render_template("tickets.html", tickets=visible, statut_filter=statut_filter)


@app.route("/ticket/<ticket_id>")
@login_required
def ticket_detail(ticket_id):
    user = current_user()
    if user["role"] == "pilote":
        abort(403)
    tickets = load_tickets()
    ticket = tickets.get(ticket_id)
    if not ticket:
        abort(404)
    if user["role"] != "admin" and ticket["centre"] != user["centre"]:
        abort(403)
    sim = load_simulation(ticket["simulation_id"])
    event = None
    if sim and 0 <= ticket["event_index"] < len(sim.get("evenements", [])):
        event = sim["evenements"][ticket["event_index"]]
    return render_template("ticket.html", ticket=ticket, sim=sim, event=event)


@app.route("/ticket/<ticket_id>/commenter", methods=["POST"])
@login_required
def ticket_commenter(ticket_id):
    user = current_user()
    if user["role"] == "pilote":
        abort(403)
    tickets = load_tickets()
    ticket = tickets.get(ticket_id)
    if not ticket:
        abort(404)
    if user["role"] != "admin" and ticket["centre"] != user["centre"]:
        abort(403)
    texte = request.form.get("texte", "").strip()
    if texte:
        ticket["commentaires"].append({
            "auteur": user["username"],
            "auteur_nom": f"{user['nom']} ({user['role']})",
            "date": datetime.now().isoformat(timespec="seconds"),
            "texte": texte,
        })
        save_tickets(tickets)
    return redirect(url_for("ticket_detail", ticket_id=ticket_id))


@app.route("/ticket/<ticket_id>/statut", methods=["POST"])
@role_required("admin")
def ticket_statut(ticket_id):
    tickets = load_tickets()
    ticket = tickets.get(ticket_id)
    if not ticket:
        abort(404)
    nouveau = request.form.get("statut")
    if nouveau in STATUT_LABELS:
        ticket["statut"] = nouveau
        ticket["resolution"] = request.form.get("resolution", "").strip() or None
        save_tickets(tickets)
        flash(f"Statut du ticket mis à jour : {STATUT_LABELS[nouveau]}.", "success")
    return redirect(url_for("ticket_detail", ticket_id=ticket_id))


# ---------------------------------------------------------------------------
# Routes : administration
# ---------------------------------------------------------------------------
@app.route("/admin")
@role_required("admin")
def admin_dashboard():
    sims = list_simulations()
    tickets = load_tickets()
    centres = load_centres()
    stats = {}
    for code, c in centres.items():
        c_sims = [s for s in sims if s.get("centre") == code]
        c_tickets = [t for t in tickets.values() if t["centre"] == code]
        stats[code] = {
            "nom": c["nom"],
            "simulations": len(c_sims),
            "tickets_ouverts": sum(1 for t in c_tickets if t["statut"] in ("ouvert", "en_cours")),
            "tickets_total": len(c_tickets),
        }
    audit = load_audit()
    return render_template(
        "admin.html",
        stats=stats,
        simulations=sims,
        tickets=sorted(tickets.values(), key=lambda t: t["date"], reverse=True),
        audit=list(reversed(audit))[:15],
    )


@app.route("/admin/edit/<sim_id>", methods=["GET", "POST"])
@role_required("admin")
def admin_edit(sim_id):
    raw = load_simulation_raw(sim_id)
    if raw is None:
        abort(404)
    ticket_id = request.args.get("ticket")

    if request.method == "POST":
        contenu = request.form.get("contenu_json", "")
        try:
            new_data = json.loads(contenu)
        except json.JSONDecodeError as e:
            flash(f"JSON invalide : {e}", "error")
            return render_template("admin_edit.html", sim_id=sim_id,
                                   contenu_json=contenu, ticket_id=ticket_id)

        env = new_data.setdefault("logsim", {})
        old_env = raw.get("logsim", {}) or {}
        old_version = old_env.get("version", 1)
        now = datetime.now().isoformat(timespec="seconds")
        env["version"] = old_version + 1
        env["date_modification"] = now
        if isinstance(new_data.get("properties"), dict):
            new_data["properties"]["update_date"] = now

        live_path = _sim_path(sim_id) or os.path.join(SIM_DIR, f"{sim_id}{SIM_EXT}")
        backup_path = os.path.join(os.path.dirname(live_path), f"{sim_id}.v{old_version}.bak{SIM_EXT}")
        _save(backup_path, raw)
        save_simulation_raw(sim_id, new_data)

        new_version = env["version"]
        audit = load_audit()
        audit.append({
            "date": now,
            "admin": current_user()["username"],
            "simulation_id": sim_id,
            "action": "modification .simlog",
            "ticket_id": request.form.get("ticket_id") or None,
            "version_avant": old_version,
            "version_apres": new_version,
        })
        save_audit(audit)

        linked = request.form.get("ticket_id")
        if linked:
            tickets = load_tickets()
            if linked in tickets:
                tickets[linked]["statut"] = "resolu"
                tickets[linked]["resolution"] = f"Appliqué dans la version {new_version}."
                save_tickets(tickets)

        flash(f"Simulation {sim_id} enregistrée (version {new_version}).", "success")
        return redirect(url_for("admin_dashboard"))

    contenu_json = json.dumps(raw, ensure_ascii=False, indent=2)
    return render_template("admin_edit.html", sim_id=sim_id,
                           contenu_json=contenu_json, ticket_id=ticket_id)


@app.errorhandler(403)
def forbidden(e):
    return render_template("error.html", code=403,
                           message="Accès refusé."), 403


@app.errorhandler(404)
def not_found(e):
    return render_template("error.html", code=404,
                           message="Page ou simulation introuvable."), 404


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
