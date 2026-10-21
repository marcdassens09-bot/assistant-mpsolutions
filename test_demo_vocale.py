# -*- coding: utf-8 -*-
"""Tests de la page de demo vocale cachee (sans appeler Retell pour de vrai).

Lancer :  python -m pytest test_demo_vocale.py -q
"""
import io
import json
import os
import urllib.error
from unittest import mock

os.environ.setdefault("ANTHROPIC_API_KEY", "test")
os.environ.setdefault("OPENAI_API_KEY", "test")

import pytest  # noqa: E402

import hardened_app  # noqa: E402

CODE = "code-secret-de-test-123"


class FausseReponse:
    def __init__(self, statut, corps, entetes=None):
        self.status = statut
        self._corps = corps
        self.headers = entetes or {}

    def read(self):
        return self._corps

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("DEMO_VOCALE_CODE", CODE)
    monkeypatch.setenv("RETELL_DEMO_AGENT_ID", "agent_demo_123")
    monkeypatch.setenv("RETELL_API_KEY", "key_test")
    app = hardened_app.app
    app.config["TESTING"] = True
    app.config["RATELIMIT_ENABLED"] = False
    hardened_app.secured.limiter.enabled = False
    with app.test_client() as c:
        yield c
    hardened_app.secured.limiter.enabled = True


def test_mauvais_code_404(client):
    assert client.get("/demo-vocale/mauvais-code-xxxxx").status_code == 404
    assert client.post("/demo-vocale/mauvais-code-xxxxx/v3/create-web-call", json={}).status_code == 404


def test_page_fermee_sans_code_configure(client, monkeypatch):
    monkeypatch.setenv("DEMO_VOCALE_CODE", "")
    assert client.get("/demo-vocale/").status_code == 404
    monkeypatch.setenv("DEMO_VOCALE_CODE", "court")
    assert client.get("/demo-vocale/court").status_code == 404


def test_page_ok(client):
    rep = client.get(f"/demo-vocale/{CODE}")
    assert rep.status_code == 200
    page = rep.get_data(as_text=True)
    assert "Parlez à l'assistante" in page
    assert f'"/demo-vocale/{CODE}"' in page
    assert "key_test" not in page  # la vraie clé ne part jamais au navigateur
    assert rep.headers["X-Robots-Tag"].startswith("noindex")


def test_relais_impose_agent_et_cle(client):
    vu = {}

    def faux_urlopen(req, timeout):
        vu["url"] = req.full_url
        vu["auth"] = req.get_header("Authorization")
        vu["corps"] = json.loads(req.data)
        return FausseReponse(
            201,
            b'{"call_id":"call_1","access_token":"tok"}',
            {"X-Retell-Client-JS-SDK-Min-Version": "3.0.0"},
        )

    with mock.patch("demo_vocale.urllib.request.urlopen", faux_urlopen):
        rep = client.post(
            f"/demo-vocale/{CODE}/v3/create-web-call",
            json={"agent_id": "agent_pirate", "agent_override": {"x": 1}},
        )
    assert rep.status_code == 201
    assert rep.get_json()["access_token"] == "tok"
    assert rep.headers["X-Retell-Client-JS-SDK-Min-Version"] == "3.0.0"
    assert vu["url"] == "https://api.retellai.com/v3/create-web-call"
    assert vu["auth"] == "Bearer key_test"
    assert vu["corps"] == {"agent_id": "agent_demo_123", "metadata": {"source": "demo-vocale"}}


def test_relais_erreur_retell_transmise(client):
    def faux_urlopen(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 402, "Payment", {}, io.BytesIO(b'{"error_message":"credit"}'))

    with mock.patch("demo_vocale.urllib.request.urlopen", faux_urlopen):
        rep = client.post(f"/demo-vocale/{CODE}/v3/create-web-call", json={})
    assert rep.status_code == 402
    assert rep.get_json()["error_message"] == "credit"


def test_agent_manquant(client, monkeypatch):
    monkeypatch.setenv("RETELL_DEMO_AGENT_ID", "")
    rep = client.post(f"/demo-vocale/{CODE}/v3/create-web-call", json={})
    assert rep.status_code == 503


def test_stop_call(client):
    vu = {}

    def faux_urlopen(req, timeout):
        vu["url"] = req.full_url
        return FausseReponse(204, b"")

    with mock.patch("demo_vocale.urllib.request.urlopen", faux_urlopen):
        rep = client.post(f"/demo-vocale/{CODE}/v2/stop-call/call_abc-1")
    assert rep.status_code == 204
    assert vu["url"] == "https://api.retellai.com/v2/stop-call/call_abc-1"
    assert client.post(f"/demo-vocale/{CODE}/v2/stop-call/bad$id").status_code == 400


def test_diag(client, capsys):
    rep = client.post(f"/demo-vocale/{CODE}/diag", json={"fin": "coupure", "ice_failed": "oui @7.0s", "objet": {"x": 1}})
    assert rep.status_code == 204
    sortie = capsys.readouterr().out
    assert "coupure" in sortie and "objet" not in sortie
    assert client.post("/demo-vocale/mauvais-code-xxxxx/diag", json={}).status_code == 404
