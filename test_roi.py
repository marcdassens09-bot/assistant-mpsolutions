import unittest

from roi import calculer_roi


class CalculRoiTest(unittest.TestCase):
    def test_professionnel_seul(self):
        resultat = calculer_roi(250, 4, 5, "seul")
        self.assertEqual(resultat["ca_mensuel_potentiel"], 500.0)
        self.assertEqual(resultat["ca_annuel_potentiel"], 6000.0)
        self.assertEqual(resultat["cout_premiere_annee"], 1520.0)
        self.assertEqual(resultat["cout_annees_suivantes"], 720.0)
        self.assertEqual(resultat["taux_couverture_pourcent"], 394.74)
        self.assertEqual(resultat["delai_amortissement_mois"], 3.04)

    def test_entreprise_avec_personnel(self):
        resultat = calculer_roi(100, 10, 2, "personnel")
        self.assertEqual(resultat["ca_annuel_potentiel"], 2400.0)
        self.assertEqual(resultat["cout_premiere_annee"], 2640.0)
        self.assertEqual(resultat["cout_annees_suivantes"], 1440.0)

    def test_zero_ne_promet_pas_amortissement(self):
        resultat = calculer_roi(100, 0, 5, "seul")
        self.assertEqual(resultat["ca_annuel_potentiel"], 0.0)
        self.assertIsNone(resultat["delai_amortissement_mois"])

    def test_refuse_donnee_manquante(self):
        with self.assertRaises(ValueError):
            calculer_roi(None, 3, 5, "seul")

    def test_refuse_plus_de_dix_clients(self):
        with self.assertRaises(ValueError):
            calculer_roi(100, 3, 11, "seul")


if __name__ == "__main__":
    unittest.main()
