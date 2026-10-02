"""Calculs déterministes du diagnostic commercial MP Solutions IA."""

from decimal import Decimal, ROUND_HALF_UP


def _nombre_positif(valeur, nom, maximum=None):
    try:
        nombre = Decimal(str(valeur))
    except Exception as exc:
        raise ValueError(f"{nom} doit être un nombre.") from exc
    if not nombre.is_finite() or nombre < 0:
        raise ValueError(f"{nom} doit être positif ou nul.")
    if maximum is not None and nombre > maximum:
        raise ValueError(f"{nom} ne peut pas dépasser {maximum}.")
    return nombre


def _arrondir(valeur, decimales="0.01"):
    return float(valeur.quantize(Decimal(decimales), rounding=ROUND_HALF_UP))


def calculer_roi(valeur_client, demandes_perdues_mois, clients_sur_dix, structure=None):
    """Retourne le chiffre d'affaires potentiel, fondé uniquement sur les données fournies.

    Aucun tarif MP Solutions IA n'est utilisé ni renvoyé : le prix se discute
    avec Marc-Paul, jamais au premier contact. `structure` est ignoré
    (gardé pour compatibilité avec d'anciens appels).
    """
    valeur = _nombre_positif(valeur_client, "valeur_client")
    demandes = _nombre_positif(demandes_perdues_mois, "demandes_perdues_mois")
    clients = _nombre_positif(clients_sur_dix, "clients_sur_dix", Decimal("10"))

    taux = clients / Decimal("10")
    ca_mensuel = valeur * demandes * taux
    ca_annuel = ca_mensuel * Decimal("12")

    return {
        "taux_transformation_pourcent": _arrondir(taux * Decimal("100")),
        "ca_mensuel_potentiel": _arrondir(ca_mensuel),
        "ca_annuel_potentiel": _arrondir(ca_annuel),
        "avertissement": (
            "Cette estimation dépend de vos chiffres et ne garantit pas une vente."
        ),
    }
