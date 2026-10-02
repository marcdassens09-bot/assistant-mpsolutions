import unittest

from roi import calculer_roi


class CalculRoiTest(unittest.TestCase):
    def test_chiffre_affaires_potentiel(self):
        resultat = calculer_roi(250, 4, 5)
        self.assertEqual(resultat["ca_mensuel_potentiel"], 500.0)
        self.assertEqual(resultat["ca_annuel_potentiel"], 6000.0)
        self.assertEqual(resultat["taux_transformation_pourcent"], 50.0)

    def test_aucun_prix_ni_donnee_permettant_de_le_retrouver(self):
        resultat = calculer_roi(100, 10, 2, "personnel")
        for cle in ("cout_premiere_annee", "cout_annees_suivantes",
                    "taux_couverture_pourcent", "delai_amortissement_mois"):
            self.assertNotIn(cle, resultat)
        texte = str(resultat)
        for montant in ("800", "1200", "1520", "2640", "720", "1440"):
            self.assertNotIn(montant, texte)

    def test_zero(self):
        resultat = calculer_roi(100, 0, 5)
        self.assertEqual(resultat["ca_annuel_potentiel"], 0.0)

    def test_refuse_donnee_manquante(self):
        with self.assertRaises(ValueError):
            calculer_roi(None, 3, 5)

    def test_refuse_plus_de_dix_clients(self):
        with self.assertRaises(ValueError):
            calculer_roi(100, 3, 11)


if __name__ == "__main__":
    unittest.main()
