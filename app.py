"""
Gestionnaire de logs de simulation ATC
Backend Flask — stockage en fichiers JSON, authentification par session,
isolation stricte par centre et filtrage des données selon le profil.
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

def load_simulation(sim_id):
    path = os.path.join(SIM_DIR, f"{sim_id}.json")
    if not os.path.exists(path):
        return None
    return _load(path)

def save_simulation(sim_id, data):
    _save(os.path.join(SIM_DIR, f"{sim_id}.json"), data)

def list_simulations():
    sims = []
    for path in sorted(glob.glob(os.path.join(SIM_DIR, "*.json"))):
        data = _load(path)
        if data:
            sims.append(data)
    return sims


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
    tickets = load_tickets()
    open_counts = {}
    for t in tickets.values():
        if t["statut"] in ("ouvert", "en_cours"):
            open_counts[t["simulation_id"]] = open_counts.get(t["simulation_id"], 0) + 1
    return render_template("simulations.html", simulations=sims, open_counts=open_counts)


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
    sim = load_simulation(sim_id)
    if not sim:
        abort(404)
    ticket_id = request.args.get("ticket")

    if request.method == "POST":
        raw = request.form.get("contenu_json", "")
        try:
            new_data = json.loads(raw)
        except json.JSONDecodeError as e:
            flash(f"JSON invalide : {e}", "error")
            return render_template("admin_edit.html", sim_id=sim_id,
                                   contenu_json=raw, ticket_id=ticket_id)
        old_version = sim.get("version", 1)
        new_data["version"] = old_version + 1
        new_data["date_modification"] = datetime.now().isoformat(timespec="seconds")
        backup_path = os.path.join(SIM_DIR, f"{sim_id}.v{old_version}.bak.json")
        _save(backup_path, sim)
        save_simulation(sim_id, new_data)

        audit = load_audit()
        audit.append({
            "date": datetime.now().isoformat(timespec="seconds"),
            "admin": current_user()["username"],
            "simulation_id": sim_id,
            "action": "modification JSON",
            "ticket_id": request.form.get("ticket_id") or None,
            "version_avant": old_version,
            "version_apres": new_data["version"],
        })
        save_audit(audit)

        linked = request.form.get("ticket_id")
        if linked:
            tickets = load_tickets()
            if linked in tickets:
                tickets[linked]["statut"] = "resolu"
                tickets[linked]["resolution"] = f"Appliqué dans la version {new_data['version']}."
                save_tickets(tickets)

        flash(f"Simulation {sim_id} enregistrée (version {new_data['version']}).", "success")
        return redirect(url_for("admin_dashboard"))

    contenu_json = json.dumps(sim, ensure_ascii=False, indent=2)
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
