"""
reporting_dashboard.py — MP Solutions IA
Blueprint Flask du dashboard client. À enregistrer dans app_XXX.py :

    from reporting_dashboard import reporting_bp
    app.register_blueprint(reporting_bp)

Variables d'environnement à ajouter sur Render pour chaque client :
    REPORTING_PASSWORD    -> mot de passe du dashboard (choisis-en un par client)
    REPORTING_LOG_PATH    -> ex: "fumeco_chat.log"
    REPORTING_CLIENT_NAME -> ex: "Fumeco-Lèze"

Accès : https://<url-render-du-client>/reporting
(authentification HTTP basique — le navigateur demande user/mot de passe,
 le champ "utilisateur" peut rester vide)
"""

import os
from functools import wraps
from flask import Blueprint, render_template, request, Response, jsonify

from reporting_stats import load_events, compute_stats

reporting_bp = Blueprint("reporting", __name__)

REPORTING_PASSWORD = os.environ.get("REPORTING_PASSWORD", "")
LOG_PATH = os.environ.get("REPORTING_LOG_PATH", "chat_events.jsonl")
CLIENT_NAME = os.environ.get("REPORTING_CLIENT_NAME", "Votre assistant")


def check_auth(password):
    return bool(REPORTING_PASSWORD) and password == REPORTING_PASSWORD


def authenticate():
    return Response(
        "Accès refusé — mot de passe requis.", 401,
        {"WWW-Authenticate": 'Basic realm="Reporting MP Solutions IA"'}
    )


def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not check_auth(auth.password):
            return authenticate()
        return f(*args, **kwargs)
    return decorated


@reporting_bp.route("/reporting")
@requires_auth
def reporting_dashboard():
    events = load_events(LOG_PATH, days=30)
    stats = compute_stats(events)
    return render_template(
        "reporting_dashboard.html",
        stats=stats,
        client_name=CLIENT_NAME,
    )


@reporting_bp.route("/reporting/api")
@requires_auth
def reporting_api():
    """Mêmes statistiques que /reporting, en JSON — pour un agent ou un
    script externe (digest automatique, etc.) plutôt qu'un navigateur."""
    events = load_events(LOG_PATH, days=30)
    stats = compute_stats(events)
    return jsonify({"client_name": CLIENT_NAME, **stats})
