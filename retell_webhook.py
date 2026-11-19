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
    APPEL_DESTINATAIRE   qui recoit les messages, une ou plusieurs adresses separees par des virgules (defaut contact@mpsolutionsia.fr)
    FICHE_EXPEDITEUR     adresse d'envoi verifiee dans Brevo
                         (defaut contact@mpsolutionsia.fr)

  SMS (facultatif, en plus de l'email) :
    BREVO_SMS_API_KEY        cle Brevo dediee (droit "SMS transactionnels")
    APPEL_SMS_DESTINATAIRE   un ou plusieurs portables separes par des virgules
                             (ex. "06 12 34 56 78, +33 7 98 76 54 32").
                             Vide ou absent = pas de SMS.
    SMS_EXPEDITEUR           nom affiche (11 lettres/chiffres max, defaut MPSolutions)

  Le SMS est "transactionnel" (pas de code STOP), en caracteres simples
  (sans accents) et coupe a 160 caracteres pour ne compter que pour 1 SMS.
  Doc Brevo verifiee le 19/11/2026 :
  https://developers.brevo.com/docs/transactional-sms-endpoints
"""

import hashlib
import hmac
import html
import json
import os
import re
import threading
import time
import unicodedata
import urllib.error
import urllib.request
from collections import OrderedDict
from datetime import datetime
from zoneinfo import ZoneInfo

from flask import request

from app import app, limiter

BREVO_URL_ENVOI = "https://api.brevo.com/v3/smtp/email"
BREVO_URL_SMS = "https://api.brevo.com/v3/transactionalSMS/send"
SMS_MAX = 160  # 1 seul SMS en caracteres simples (GSM 7 bits)
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
        # Une ou plusieurs adresses, separees par des virgules (ex. le parent et un proche)
        "to": [{"email": a.strip()} for a in
               os.environ.get("APPEL_DESTINATAIRE", "contact@mpsolutionsia.fr").split(",")
               if a.strip()],
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


# ── SMS (Brevo, facultatif) ──────────────────────────────────────────────────

# Caracteres de l'alphabet GSM de base (1 caractere = 1 place sur 160).
_GSM_BASE = set(
    "@£$¥\n\rΔ_ !\"#%&'()*+,-./0123456789:;<=>?"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
)
_REMPLACEMENTS = {
    "’": "'", "‘": "'", "“": '"', "”": '"', "«": '"', "»": '"',
    "—": "-", "–": "-", "…": "...", "[": "(", "]": ")", "{": "(", "}": ")",
    "œ": "oe", "Œ": "OE", "æ": "ae", "Æ": "AE", "ß": "ss",
    "€": "EUR", "\u00a0": " ", "\n": " ", "\r": " ", "\t": " ",
}


def texte_sms(texte):
    """Enleve accents et caracteres speciaux : il ne reste que du GSM de base."""
    for avant, apres in _REMPLACEMENTS.items():
        texte = texte.replace(avant, apres)
    texte = unicodedata.normalize("NFKD", texte)
    texte = "".join(c for c in texte if not unicodedata.combining(c))
    texte = "".join(c if c in _GSM_BASE else " " for c in texte)
    return re.sub(r"\s+", " ", texte).strip()


def numero_sms(brut):
    """Met un numero au format Brevo (indicatif, sans +). None si pas un portable.

    "06 12 34 56 78" -> "33612345678" ; "+33 7..." -> "337..." ;
    autre pays en "+xx..." ou "00xx..." garde tel quel.
    """
    chiffres = re.sub(r"[^\d+]", "", brut or "")
    if chiffres.startswith("+"):
        chiffres = chiffres[1:]
    elif chiffres.startswith("00"):
        chiffres = chiffres[2:]
    elif chiffres.startswith("0"):
        chiffres = "33" + chiffres[1:]
    if not chiffres.isdigit():
        return None
    if chiffres.startswith("33"):
        # France : seuls les portables (06, 07) recoivent les SMS
        if len(chiffres) != 11 or chiffres[2] not in "67":
            return None
    elif not 8 <= len(chiffres) <= 15:
        return None
    return chiffres


def preparer_sms(call):
    """Texte court : qui, son numero, pourquoi. 160 caracteres maximum."""
    champs = (call.get("call_analysis") or {}).get("custom_analysis_data") or {}
    appelant = texte_sms(_texte(champs.get("appelant"), "inconnu"))
    entreprise = texte_sms(str(champs.get("entreprise") or "").strip())
    if entreprise.lower() in ("", "non indique", "aucune", "particulier"):
        entreprise = ""
    telephone = texte_sms(str(champs.get("telephone") or "").strip()) or "non donne"
    motif = texte_sms(_texte(champs.get("motif"), "non precise"))

    qui = appelant + (f" ({entreprise})" if entreprise else "")
    debut = f"Appel de {qui}, tel {telephone}. Motif : "
    fin = " - MP Solutions IA"
    place = SMS_MAX - len(debut) - len(fin)
    if place < 10:  # nom tres long : on raccourcit le debut
        debut = debut[: SMS_MAX - len(fin) - 13] + "... Motif : "
        place = SMS_MAX - len(debut) - len(fin)
    if len(motif) > place:
        motif = motif[: place - 3].rstrip() + "..."
    return (debut + motif + fin)[:SMS_MAX]


def _envoyer_sms(texte, call_id):
    cle = (os.environ.get("BREVO_SMS_API_KEY") or "").strip()
    brut = os.environ.get("APPEL_SMS_DESTINATAIRE", "")
    numeros = [n for n in (numero_sms(x) for x in brut.split(",") if x.strip()) if n]
    if not brut.strip():
        return  # pas de SMS demande
    if not cle:
        print("[retell] SMS non envoye : BREVO_SMS_API_KEY absente", flush=True)
        return
    if not numeros:
        print("[retell] SMS non envoye : aucun numero de portable valide", flush=True)
        return
    expediteur = re.sub(r"[^A-Za-z0-9]", "",
                        os.environ.get("SMS_EXPEDITEUR", "MPSolutions"))[:11] or "MPSolutions"
    for numero in numeros:
        payload = {
            "sender": expediteur,
            "recipient": numero,
            "content": texte,
            "type": "transactional",
            "tag": "appel-assistant",
        }
        req = urllib.request.Request(
            BREVO_URL_SMS,
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={
                "api-key": cle,
                "accept": "application/json",
                "content-type": "application/json",
            },
        )
        fin_numero = numero[-2:]
        try:
            with urllib.request.urlopen(req, timeout=10) as rep:
                print(f"[retell] SMS envoye pour {call_id} (..{fin_numero}, HTTP {rep.status})",
                      flush=True)
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300]
            print(f"[retell] ECHEC SMS ..{fin_numero} HTTP {e.code} : {detail}", flush=True)
        except Exception as e:
            print(f"[retell] ECHEC SMS ..{fin_numero} : {e}", flush=True)


def _envoyer_tout(sujet, corps_html, corps_texte, texte_court, call_id):
    _envoyer(sujet, corps_html, corps_texte, call_id)
    _envoyer_sms(texte_court, call_id)


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
    texte_court = preparer_sms(call)
    # On repond tout de suite a Retell (limite 10 s), l'email et le SMS partent a cote.
    threading.Thread(
        target=_envoyer_tout,
        args=(sujet, corps_html, corps_texte, texte_court, call_id),
        daemon=True,
    ).start()
    return "", 204
