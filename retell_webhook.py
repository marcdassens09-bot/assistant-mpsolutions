# -*- coding: utf-8 -*-
"""Webhook Retell : chaque appel de l'agent vocal arrive par email.

Retell appelle POST /retell-webhook a la fin de chaque appel. On ne traite
que l'evenement "call_analyzed" (c'est le seul qui contient les 4 champs
extraits : appelant, entreprise, telephone, motif) et on envoie un email
recapitulatif via l'API Brevo (meme methode que le chatbot du camping).

Doc verifiee le 14/10/2026 :
  - https://docs.retellai.com/features/webhook
  - https://docs.retellai.com/features/secure-webhook
  - https://docs.retellai.com/api-references/get-call

Variables d'environnement (Render > Environment) :
    RETELL_API_KEY       cle API Retell qui porte le badge "webhook"
                         (obligatoire : sans elle, tout est refuse)
    BREVO_API_KEY        cle API Brevo (obligatoire pour l'envoi)
    APPEL_DESTINATAIRE   qui recoit les messages (defaut contact@mpsolutionsia.fr)
    FICHE_EXPEDITEUR     adresse d'envoi verifiee dans Brevo
                         (defaut contact@mpsolutionsia.fr)
"""

import hashlib
import hmac
import html
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from collections import OrderedDict
from datetime import datetime
from zoneinfo import ZoneInfo

from flask import request

from app import app, limiter

BREVO_URL_ENVOI = "https://api.brevo.com/v3/smtp/email"
TOLERANCE_MS = 5 * 60 * 1000  # Retell : refuser une signature de plus de 5 min
MOTIF_SIGNATURE = re.compile(r"v=(\d+),d=([0-9a-fA-F]+)")

# Retell renvoie jusqu'a 3 fois si on ne repond pas assez vite :
# on garde les derniers call_id traites pour ne pas envoyer 2 emails.
# (En memoire : un redemarrage du service vide cette liste.)
_deja_traites = OrderedDict()
_verrou = threading.Lock()
MAX_MEMOIRE = 500


# ── Signature ────────────────────────────────────────────────────────────────

def signature_valide(corps_brut, entete, cle, maintenant_ms=None):
    """Verifie l'en-tete X-Retell-Signature : "v=<timestamp ms>,d=<hex>".

    digest attendu = HMAC-SHA256(corps_brut + timestamp, cle), en hexadecimal.
    """
    if not entete or not cle:
        return False
    trouve = MOTIF_SIGNATURE.fullmatch(entete.strip())
    if not trouve:
        return False
    horodatage, digest_recu = trouve.group(1), trouve.group(2)
    if maintenant_ms is None:
        maintenant_ms = int(time.time() * 1000)
    if abs(maintenant_ms - int(horodatage)) > TOLERANCE_MS:
        return False
    attendu = hmac.new(
        cle.encode("utf-8"),
        corps_brut.encode("utf-8") + horodatage.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(attendu, digest_recu.lower())


def _premiere_fois(call_id):
    with _verrou:
        if call_id in _deja_traites:
            return False
        _deja_traites[call_id] = True
        while len(_deja_traites) > MAX_MEMOIRE:
            _deja_traites.popitem(last=False)
        return True


# ── Mise en forme du message ─────────────────────────────────────────────────

def _texte(valeur, defaut="non indiqué"):
    valeur = str(valeur or "").strip()
    return valeur if valeur else defaut


def preparer_email(call):
    """Construit (sujet, corps_html, corps_texte) a partir de l'objet call."""
    analyse = call.get("call_analysis") or {}
    champs = analyse.get("custom_analysis_data") or {}

    appelant = _texte(champs.get("appelant"))
    entreprise = _texte(champs.get("entreprise"))
    telephone = _texte(champs.get("telephone"))
    motif = _texte(champs.get("motif"))
    resume = _texte(analyse.get("call_summary"), "")

    canal = "Appel web (site)" if call.get("call_type") == "web_call" else "Téléphone"
    numero_entrant = call.get("from_number") or ""

    debut = call.get("start_timestamp")
    quand = "?"
    if debut:
        quand = datetime.fromtimestamp(debut / 1000, ZoneInfo("Europe/Paris")).strftime(
            "%d/%m/%Y à %H:%M"
        )
    duree_ms = call.get("duration_ms") or 0
    duree = f"{int(duree_ms // 60000)} min {int(duree_ms % 60000 // 1000):02d} s"

    sujet = f"\U0001F4DE Nouveau message de {appelant} — {entreprise}"

    lignes = [
        ("Nom", appelant),
        ("Entreprise", entreprise),
        ("Téléphone", telephone),
        ("Motif", motif),
    ]
    infos = [("Reçu le", quand), ("Durée", duree), ("Canal", canal)]
    if numero_entrant:
        infos.append(("Numéro entrant", numero_entrant))

    def _tableau(paires):
        return "".join(
            f"<tr><td style='padding:4px 12px 4px 0;color:#E8730A'><b>{html.escape(k)}</b></td>"
            f"<td style='padding:4px 0;color:#1b3a2b'>{html.escape(v)}</td></tr>"
            for k, v in paires
        )

    corps_html = (
        "<div style='font-family:Arial,sans-serif;color:#1b3a2b'>"
        "<p><b>L'assistant vocal a pris un message.</b></p>"
        f"<table>{_tableau(lignes)}</table>"
        + (f"<p><b style='color:#E8730A'>Résumé :</b><br>{html.escape(resume)}</p>" if resume else "")
        + f"<p style='color:#888;font-size:12px'><table>{_tableau(infos)}</table></p>"
        "<p style='color:#888;font-size:12px'>Assistant vocal MP Solutions IA (Retell)</p>"
        "</div>"
    )
    corps_texte = (
        "L'assistant vocal a pris un message.\n\n"
        + "\n".join(f"{k} : {v}" for k, v in lignes)
        + (f"\n\nRésumé : {resume}" if resume else "")
        + "\n\n"
        + "\n".join(f"{k} : {v}" for k, v in infos)
        + "\n-- Assistant vocal MP Solutions IA"
    )
    return sujet, corps_html, corps_texte


# ── Envoi Brevo (en arriere-plan) ────────────────────────────────────────────

def _envoyer(sujet, corps_html, corps_texte, call_id):
    cle = (os.environ.get("BREVO_API_KEY") or "").strip()
    if not cle:
        print("[retell] ECHEC : BREVO_API_KEY absente", flush=True)
        return
    payload = {
        "sender": {
            "name": "Assistant vocal MP Solutions IA",
            "email": os.environ.get("FICHE_EXPEDITEUR", "contact@mpsolutionsia.fr"),
        },
        "to": [{"email": os.environ.get("APPEL_DESTINATAIRE", "contact@mpsolutionsia.fr")}],
        "subject": sujet,
        "htmlContent": corps_html,
        "textContent": corps_texte,
    }
    req = urllib.request.Request(
        BREVO_URL_ENVOI,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "api-key": cle,
            "accept": "application/json",
            "content-type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as rep:
            print(f"[retell] email envoye pour {call_id} (HTTP {rep.status})", flush=True)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        print(f"[retell] ECHEC Brevo HTTP {e.code} : {detail}", flush=True)
    except Exception as e:
        print(f"[retell] ECHEC envoi : {e}", flush=True)


# ── Route ────────────────────────────────────────────────────────────────────

@app.route("/retell-webhook", methods=["POST"])
@limiter.exempt
def retell_webhook():
    corps_brut = request.get_data(as_text=True)
    cle = (os.environ.get("RETELL_API_KEY") or "").strip()
    if not signature_valide(corps_brut, request.headers.get("X-Retell-Signature"), cle):
        print("[retell] signature refusee", flush=True)
        return "", 401

    try:
        donnees = json.loads(corps_brut)
    except ValueError:
        return "", 400

    evenement = donnees.get("event")
    call = donnees.get("call") or {}
    call_id = call.get("call_id") or "?"

    if evenement != "call_analyzed":
        return "", 204  # call_started / call_ended : rien a faire

    if not _premiere_fois(call_id):
        print(f"[retell] doublon ignore : {call_id}", flush=True)
        return "", 204

    sujet, corps_html, corps_texte = preparer_email(call)
    # On repond tout de suite a Retell (limite 10 s), l'email part a cote.
    threading.Thread(
        target=_envoyer, args=(sujet, corps_html, corps_texte, call_id), daemon=True
    ).start()
    return "", 204
