# -*- coding: utf-8 -*-
"""Page de demo cachee : parler a l'assistante vocale (Retell) depuis le navigateur.

But : en visite chez un prospect, Marc-Paul ouvre cette page sur son telephone,
appuie sur le bouton, et le prospect parle a l'assistante. Le mail recapitulatif
arrive ensuite comme pour un vrai appel (webhook /retell-webhook, inchange).

Adresse : https://<service>/demo-vocale/<DEMO_VOCALE_CODE>
  - sans le bon code -> 404 (la page "n'existe pas")
  - la cle Retell reste sur le serveur : le navigateur passe par le relais
    /demo-vocale/<code>/v3/create-web-call, qui impose l'agent de demo.

Doc verifiee le 21/10/2026 :
  - https://docs.retellai.com/api-references/create-web-call  (POST /v3/create-web-call)
  - README de retell-client-js-sdk 3.0.2 (RetellClient + option `fetch` = relais)

Variables d'environnement (Render > Environment) :
    DEMO_VOCALE_CODE       code secret dans l'adresse (obligatoire, 12 caracteres mini)
    RETELL_DEMO_AGENT_ID   identifiant de l'agent Retell (agent_...) (obligatoire)
    RETELL_API_KEY         deja present (sert aussi au webhook)
"""

import hmac
import json
import os
import re
import urllib.error
import urllib.request

from flask import Response, abort, render_template, request

from app import app, limiter

RETELL_HOTE = "https://api.retellai.com"
ENTETES_VERSION_SDK = (
    "X-Retell-Client-JS-SDK-Min-Version",
    "X-Retell-Client-JS-SDK-Recommended-Version",
)
MOTIF_CALL_ID = re.compile(r"[A-Za-z0-9_-]{1,100}")
TAILLE_MINI_CODE = 12


def _code_valide(code):
    attendu = os.environ.get("DEMO_VOCALE_CODE", "")
    if len(attendu) < TAILLE_MINI_CODE:
        return False  # pas de code configure (ou trop court) : page fermee
    return hmac.compare_digest(code.encode("utf-8"), attendu.encode("utf-8"))


def _verifier_code(code):
    if not _code_valide(code):
        abort(404)


def _relayer(chemin, corps):
    """Envoie la requete a Retell avec la vraie cle et renvoie sa reponse telle quelle."""
    cle = os.environ.get("RETELL_API_KEY", "")
    if not cle:
        return _erreur(503, "Demo indisponible : RETELL_API_KEY manquante.")
    entetes = {
        "Authorization": f"Bearer {cle}",
        "Content-Type": "application/json",
    }
    version_sdk = request.headers.get("X-Retell-Client-JS-SDK-Version")
    if version_sdk:
        entetes["X-Retell-Client-JS-SDK-Version"] = version_sdk[:40]
    req = urllib.request.Request(
        RETELL_HOTE + chemin,
        data=json.dumps(corps).encode("utf-8"),
        headers=entetes,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as rep:
            statut, contenu, entetes_rep = rep.status, rep.read(), rep.headers
    except urllib.error.HTTPError as err:
        statut, contenu, entetes_rep = err.code, err.read(), err.headers
        app.logger.warning("demo-vocale : Retell a repondu %s sur %s", statut, chemin)
    except (urllib.error.URLError, TimeoutError) as err:
        app.logger.error("demo-vocale : Retell injoignable (%s)", err)
        return _erreur(502, "Retell injoignable, reessayez dans un instant.")

    reponse = Response(contenu, status=statut, mimetype="application/json")
    for nom in ENTETES_VERSION_SDK:
        valeur = entetes_rep.get(nom) if entetes_rep else None
        if valeur:
            reponse.headers[nom] = valeur
    reponse.headers["Cache-Control"] = "no-store"
    return reponse


def _erreur(statut, message):
    return Response(
        json.dumps({"error_message": message}, ensure_ascii=False),
        status=statut,
        mimetype="application/json",
    )


@app.route("/demo-vocale/<code>")
@limiter.limit("20 per minute")
def demo_vocale_page(code):
    _verifier_code(code)
    reponse = Response(render_template("demo_vocale.html", code=code))
    # Le code est dans l'adresse : ne pas indexer, ne pas garder en cache.
    # (Le Referrer-Policy global n'envoie que l'origine aux autres sites ;
    #  la page ajoute en plus <meta name="referrer" content="no-referrer">.)
    reponse.headers["X-Robots-Tag"] = "noindex, nofollow"
    reponse.headers["Cache-Control"] = "no-store"
    return reponse


@app.route("/demo-vocale/<code>/v3/create-web-call", methods=["POST"])
@limiter.limit("3 per minute;40 per day")
def demo_vocale_creer_appel(code):
    _verifier_code(code)
    agent_id = os.environ.get("RETELL_DEMO_AGENT_ID", "").strip()
    if not agent_id:
        return _erreur(503, "Demo indisponible : RETELL_DEMO_AGENT_ID manquant.")
    # On ignore ce que le navigateur demande : seul l'agent de demo est autorise.
    corps = {"agent_id": agent_id, "metadata": {"source": "demo-vocale"}}
    return _relayer("/v3/create-web-call", corps)


@app.route("/demo-vocale/<code>/v2/stop-call/<call_id>", methods=["POST"])
@limiter.limit("10 per minute")
def demo_vocale_arreter_appel(code, call_id):
    """Utilise par le SDK si on raccroche pendant la mise en relation."""
    _verifier_code(code)
    if not MOTIF_CALL_ID.fullmatch(call_id):
        abort(400)
    return _relayer(f"/v2/stop-call/{call_id}", {})
