"""
reporting_stats.py — MP Solutions IA
Calcule les statistiques à partir du log JSONL écrit par reporting_logger.py
"""

import json
import os
import urllib.request
from collections import Counter
from datetime import datetime, timedelta, timezone

STOPWORDS = {
    "le", "la", "les", "de", "des", "du", "un", "une", "et", "est",
    "vous", "je", "tu", "il", "elle", "que", "qui", "pour", "dans",
    "sur", "avec", "ce", "ça", "au", "aux", "en", "à", "d", "l", "c",
    "j", "n", "s", "y", "ne", "pas", "votre", "nos", "vos",
}


def _lire_sheet(url):
    """Lit tous les événements du Google Sheet. Une erreur remonte : mieux
    vaut une page en erreur qu'un faux « 0 échange »."""
    with urllib.request.urlopen(url, timeout=30) as rep:
        donnees = json.loads(rep.read().decode("utf-8"))
    if not donnees.get("ok"):
        raise RuntimeError("Le Google Sheet a refusé la lecture (jeton invalide ?)")
    return donnees.get("events", [])


def load_events(log_path, days=30):
    """Charge les événements des N derniers jours (Google Sheet si
    REPORTING_SHEET_URL est défini, sinon fichier JSONL)."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    sheet_url = os.environ.get("REPORTING_SHEET_URL", "").strip()
    if sheet_url:
        events = []
        for ev in _lire_sheet(sheet_url):
            try:
                ev["timestamp"] = str(ev["timestamp"]).replace("Z", "+00:00")
                if datetime.fromisoformat(ev["timestamp"]) >= cutoff:
                    events.append(ev)
            except (KeyError, ValueError):
                continue
        return events
    events = []
    try:
        with open(log_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                    ts = datetime.fromisoformat(ev["timestamp"])
                    if ts >= cutoff:
                        events.append(ev)
                except (json.JSONDecodeError, KeyError, ValueError):
                    continue
    except FileNotFoundError:
        pass
    return events


def compute_stats(events):
    """Calcule toutes les métriques du dashboard à partir des événements."""
    total = len(events)
    urgent_count = sum(1 for e in events if e.get("urgent"))
    unanswered_count = sum(1 for e in events if not e.get("answered", True))

    profiles = Counter(e.get("profile", "inconnu") for e in events)

    daily = Counter()
    for e in events:
        ts = datetime.fromisoformat(e["timestamp"])
        daily[ts.strftime("%Y-%m-%d")] += 1
    daily_sorted = sorted(daily.items())[-7:]

    words = Counter()
    for e in events:
        for w in e.get("question", "").lower().split():
            w = w.strip(".,?!;:\"'()")
            if len(w) > 3 and w not in STOPWORDS:
                words[w] += 1
    top_keywords = words.most_common(8)

    return {
        "total": total,
        "urgent_count": urgent_count,
        "unanswered_count": unanswered_count,
        "profiles": dict(profiles),
        "daily": daily_sorted,
        "top_keywords": top_keywords,
    }
