"""Calculs déterministes du diagnostic commercial MP Solutions IA."""

from decimal import Decimal, ROUND_HALF_UP


TARIFS = {
    "seul": {"installation": Decimal("800"), "mensuel": Decimal("60")},
    "personnel": {"installation": Decimal("1200"), "mensuel": Decimal("120")},
}


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


def calculer_roi(valeur_client, demandes_perdues_mois, clients_sur_dix, structure):
    """Retourne une estimation fondée exclusivement sur les données fournies."""
    if structure not in TARIFS:
        raise ValueError("structure doit valoir 'seul' ou 'personnel'.")

    valeur = _nombre_positif(valeur_client, "valeur_client")
    demandes = _nombre_positif(demandes_perdues_mois, "demandes_perdues_mois")
    clients = _nombre_positif(clients_sur_dix, "clients_sur_dix", Decimal("10"))

    taux = clients / Decimal("10")
    ca_mensuel = valeur * demandes * taux
    ca_annuel = ca_mensuel * Decimal("12")
    tarif = TARIFS[structure]
    cout_premiere_annee = tarif["installation"] + tarif["mensuel"] * Decimal("12")
    cout_annees_suivantes = tarif["mensuel"] * Decimal("12")
    couverture = (
        ca_annuel / cout_premiere_annee * Decimal("100")
        if cout_premiere_annee else Decimal("0")
    )
    amortissement = (
        cout_premiere_annee / ca_mensuel if ca_mensuel else None
    )

    return {
        "taux_transformation_pourcent": _arrondir(taux * Decimal("100")),
        "ca_mensuel_potentiel": _arrondir(ca_mensuel),
        "ca_annuel_potentiel": _arrondir(ca_annuel),
        "taux_couverture_pourcent": _arrondir(couverture),
        "delai_amortissement_mois": (
            _arrondir(amortissement) if amortissement is not None else None
        ),
        "cout_premiere_annee": _arrondir(cout_premiere_annee),
        "cout_annees_suivantes": _arrondir(cout_annees_suivantes),
        "avertissement": (
            "Cette estimation dépend de vos chiffres et ne garantit pas une vente."
        ),
    }
