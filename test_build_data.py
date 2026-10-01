import unittest
from datetime import date
from unittest.mock import patch

import build_data as build


def actor(first="Camille", last="Martin"):
    return {"etatCivil": {"ident": {"prenom": first, "nom": last}}}


def profile(status="Mandat clos le 30 septembre 2026 (17<sup>e</sup> législature)", name="Mme Camille Martin"):
    return f'<h1>{name}</h1><span class="_colored _bold _big">| {status}</span>'


class MandateReconciliationTests(unittest.TestCase):
    def test_closed_profile_confirms_date_and_legislature(self):
        self.assertEqual(
            build.confirmed_closed_mandate(actor(), profile(), date(2026, 10, 1)),
            date(2026, 9, 30),
        )

    def test_active_future_other_legislature_wrong_identity_or_incomplete_rejected(self):
        cases = [
            profile("Mandat en cours"),
            profile("Mandat clos le 2 octobre 2026 (17<sup>e</sup> législature)"),
            profile("Mandat clos le 30 septembre 2026 (16<sup>e</sup> législature)"),
            profile(name="Mme Une Autre Personne"),
            '<h1>Mme Camille Martin</h1><p>Mandat clos le 30 septembre 2026 (17e législature)</p>',
        ]
        for html in cases:
            with self.subTest(html=html):
                self.assertIsNone(build.confirmed_closed_mandate(actor(), html, date(2026, 10, 1)))

    def test_matching_lists_need_no_profile_request(self):
        actors = {"PA1": actor()}
        with patch.object(build, "download_text") as download:
            self.assertEqual(build.reconcile_current_actors(actors, {"PA1": "RN"}), actors)
            download.assert_not_called()

    def test_only_confirmed_departure_is_removed(self):
        actors = {"PA1": actor(), "PA2": actor("Léa", "Dupont")}
        with patch.object(build, "download_text", return_value=profile()) as download:
            result = build.reconcile_current_actors(actors, {"PA2": "SOC"})
        self.assertEqual(set(result), {"PA2"})
        self.assertEqual(set(actors), {"PA1", "PA2"})
        download.assert_called_once_with("https://www.assemblee-nationale.fr/dyn/deputes/PA1")

    def test_unexplained_absence_remains_a_blocking_error(self):
        with patch.object(build, "download_text", return_value=profile("Mandat en cours")):
            with self.assertRaisesRegex(RuntimeError, "Décalage non résolu.*PA1"):
                build.reconcile_current_actors({"PA1": actor()}, {})

    def test_new_member_missing_from_amo_remains_a_blocking_error(self):
        with self.assertRaisesRegex(RuntimeError, "absents d'AMO40.*PA2"):
            build.reconcile_current_actors({"PA1": actor()}, {"PA1": "RN", "PA2": "SOC"})


if __name__ == "__main__":
    unittest.main()
