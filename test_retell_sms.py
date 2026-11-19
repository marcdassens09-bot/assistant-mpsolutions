# -*- coding: utf-8 -*-
"""Tests de l'envoi SMS du webhook Retell (sans appeler Brevo pour de vrai).

Lancer :  python -m pytest test_retell_sms.py -q
"""
import json
import os
from unittest import mock

os.environ.setdefault("ANTHROPIC_API_KEY", "test")
os.environ.setdefault("OPENAI_API_KEY", "test")

import hardened_app  # noqa: E402,F401
import retell_webhook as rw  # noqa: E402


def appel(**champs):
    return {"call_id": "c1", "call_analysis": {"custom_analysis_data": champs}}


def test_numeros():
    assert rw.numero_sms("06 12 34 56 78") == "33612345678"
    assert rw.numero_sms("07.98.76.54.32") == "33798765432"
    assert rw.numero_sms("+33 6 12 34 56 78") == "33612345678"
    assert rw.numero_sms("0033612345678") == "33612345678"
    assert rw.numero_sms("05 61 68 50 12") is None   # fixe : pas de SMS
    assert rw.numero_sms("") is None
    assert rw.numero_sms("+32 470 12 34 56") == "32470123456"  # Belgique


def test_texte_sans_accents_ni_crochets():
    t = rw.texte_sms("Hélène Œuvre — «devis» [Démarchage] 5 €")
    assert t == 'Helene OEuvre - "devis" (Demarchage) 5 EUR'
    assert all(c in rw._GSM_BASE for c in t)


def test_sms_court_et_complet():
    sms = rw.preparer_sms(appel(appelant="Jean Dupont", entreprise="non indiqué",
                                telephone="06 12 34 56 78", motif="Rappeler pour le devis"))
    assert sms == ("Appel de Jean Dupont, tel 06 12 34 56 78. "
                   "Motif : Rappeler pour le devis - MP Solutions IA")


def test_sms_long_coupe_a_160():
    sms = rw.preparer_sms(appel(appelant="Jean-Christophe de La Fontaine",
                                entreprise="Établissements Fontaine & Fils",
                                telephone="06 12 34 56 78", motif="x " * 200))
    assert len(sms) <= 160
    assert sms.endswith("... - MP Solutions IA")
    assert all(c in rw._GSM_BASE for c in sms)


def test_sms_nom_enorme():
    sms = rw.preparer_sms(appel(appelant="A" * 300, motif="test"))
    assert len(sms) <= 160


class Rep:
    status = 201

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_envoi_deux_numeros(monkeypatch):
    monkeypatch.setenv("BREVO_SMS_API_KEY", "cle-test")
    monkeypatch.setenv("APPEL_SMS_DESTINATAIRE", "06 12 34 56 78, 05 61 00 00 00, 07 98 76 54 32")
    envoyes = []

    def faux_urlopen(req, timeout=10):
        envoyes.append((req.full_url, req.headers, json.loads(req.data)))
        return Rep()

    with mock.patch.object(rw.urllib.request, "urlopen", faux_urlopen):
        rw._envoyer_sms("Bonjour", "c1")
    assert [e[2]["recipient"] for e in envoyes] == ["33612345678", "33798765432"]
    assert envoyes[0][0] == rw.BREVO_URL_SMS
    assert envoyes[0][1]["Api-key"] == "cle-test"
    assert envoyes[0][2]["type"] == "transactional"
    assert envoyes[0][2]["sender"] == "MPSolutions"


def test_pas_de_sms_si_rien_demande(monkeypatch):
    monkeypatch.delenv("APPEL_SMS_DESTINATAIRE", raising=False)
    monkeypatch.setenv("BREVO_SMS_API_KEY", "cle-test")
    with mock.patch.object(rw.urllib.request, "urlopen") as u:
        rw._envoyer_sms("Bonjour", "c1")
    u.assert_not_called()


def test_pas_de_sms_sans_cle(monkeypatch):
    monkeypatch.setenv("APPEL_SMS_DESTINATAIRE", "06 12 34 56 78")
    monkeypatch.delenv("BREVO_SMS_API_KEY", raising=False)
    with mock.patch.object(rw.urllib.request, "urlopen") as u:
        rw._envoyer_sms("Bonjour", "c1")
    u.assert_not_called()
