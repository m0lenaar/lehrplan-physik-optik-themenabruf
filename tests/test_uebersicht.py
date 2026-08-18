"""Tests for the standalone overview script.

The fixture reproduces the three situations seen in the live data:

* Sachsen with an asserted Jahrgangsstufe on the node
* Rheinland-Pfalz without any level, but with a title that implies Sek II
* a curriculum title carrying a grade range ("Physik 7-9/10")
"""

import unittest

import optik_uebersicht as ue


def _node(label, rollen, stufen=None, eltern=()):
    return {
        "uri": f"https://n/{abs(hash(label)) % 10000}",
        "label": label,
        "rollen": rollen,
        "klassen": [],
        "stufen": stufen or {},
        "stufen_quelle": "knoten" if stufen else "keine",
        "eltern": [{"uri": "https://p/1", "label": e} for e in eltern],
    }


def _lehrplan(label, land, treffer, stufen=None):
    return {
        "uri": f"https://lp/{abs(hash(label)) % 10000}",
        "label": label,
        "bundesland": [{"uri": "https://b/x", "label": land}],
        "schulart": [],
        "schulfach": [{"uri": "https://f/p", "label": "Physik"}],
        "stufen": stufen or {},
        "weitere": [],
        "treffer": treffer,
    }


JGS_7 = {"jahrgangsstufe": [{"uri": "https://j/7", "label": "Klassenstufe 7"}]}

RESULT = {
    "abgerufen_am": "2026-07-28T13:00:00+00:00",
    "endpoint": "https://sparql.example.org/sparql/",
    "filter": {"fach": "physik", "bundesland": None, "stichwoerter": ["Optik", "Licht", "Strahl"]},
    "anzahl": {"lehrplaene": 4, "treffer": 6},
    "lehrplaene": [
        _lehrplan(
            "Gymnasium Physik",
            "Sachsen",
            [
                _node("Lernbereich 2: Optik", ["themenbereich"], JGS_7, ["Gymnasium Physik"]),
                _node("Lichtbrechung an Linsen", ["kompetenz", "inhalt"], JGS_7, ["Lernbereich 2: Optik"]),
                _node("Wahlpflichtlernbereich 9: Astrophysik", ["themenbereich"], JGS_7, ["Gymnasium Physik"]),
            ],
        ),
        _lehrplan(
            "Lehrplan Physik, Grund- und Leistungsfach in der gymnasialen Oberstufe",
            "Rheinland-Pfalz",
            [_node("Licht sowohl als Welle als auch als Teilchen verstehen", ["kompetenz"], None, ["Lernbereich 7"])],
        ),
        _lehrplan("Physik 7-9/10", "Rheinland-Pfalz", [_node("Strahlengang am Spiegel", ["kompetenz"])]),
        _lehrplan(
            "Sachunterricht 1-4",
            "Rheinland-Pfalz",
            [
                _node(
                    "Erlebte bzw. arrangierte Phaenomene gezielt beobachten (Licht und Schatten)",
                    ["kompetenz"],
                    {"jahrgangsstufe": [{"uri": "https://j/1", "label": "Klassenstufe 1"}]},
                    ["Perspektive Natur"],
                )
            ],
        ),
    ],
    "diagnostik": {"lehrplan_praedikate": [], "klassen_ohne_rolle": []},
}


class NoiseTest(unittest.TestCase):
    def test_word_internal_match_is_noise(self):
        self.assertTrue(ue.is_noise("Wahlpflichtlernbereich 9: Astrophysik", ["Licht"]))

    def test_word_initial_match_is_kept(self):
        self.assertFalse(ue.is_noise("Lichtbrechung an Linsen", ["Licht"]))

    def test_compound_with_keyword_at_word_start_is_kept(self):
        self.assertFalse(ue.is_noise("Strahlengang am Spiegel", ["Strahl"]))

    def test_compound_with_keyword_at_word_end_is_kept(self):
        # "Wellenoptik" is on topic even though "Optik" is not the first element.
        self.assertFalse(ue.is_noise("Lernbereich 4: Wellenoptik", ["Optik"]))

    def test_keyword_buried_on_both_sides_is_noise(self):
        self.assertTrue(ue.is_noise("Waermestrahlung", ["Strahl"]))
        self.assertTrue(ue.is_noise("Roentgenstrahlung", ["Strahl"]))

    def test_label_without_any_keyword_is_not_noise(self):
        self.assertFalse(ue.is_noise("Mechanische Schwingungen", ["Licht"]))


class SchulstufeTest(unittest.TestCase):
    def test_asserted_jahrgangsstufe_maps_to_sek_i(self):
        node = _node("x", ["kompetenz"], JGS_7)
        stufe, quelle = ue.resolve_schulstufe(node, _lehrplan("Gymnasium Physik", "SN", []))
        self.assertEqual(stufe, ue.SEK_I)
        self.assertEqual(quelle, "abgeleitet aus Jahrgangsstufe")

    def test_asserted_schulstufe_wins_over_derivation(self):
        lehrplan = _lehrplan(
            "Gymnasium Physik", "SN", [], {"schulstufe": [{"uri": "https://s/2", "label": "Sekundarbereich II"}]}
        )
        stufe, quelle = ue.resolve_schulstufe(_node("x", ["kompetenz"]), lehrplan)
        self.assertEqual(stufe, ue.SEK_II)
        self.assertTrue(quelle.startswith("Daten"))

    def test_title_implies_sek_ii(self):
        lehrplan = _lehrplan("Lehrplan Physik, Grund- und Leistungsfach in der gymnasialen Oberstufe", "RP", [])
        self.assertEqual(ue.resolve_schulstufe(_node("x", ["kompetenz"]), lehrplan)[0], ue.SEK_II)

    def test_grade_range_in_title_implies_sek_i(self):
        self.assertEqual(ue.resolve_schulstufe(_node("x", ["kompetenz"]), _lehrplan("Physik 7-9/10", "RP", []))[0], ue.SEK_I)

    def test_unresolvable_level(self):
        stufe, quelle = ue.resolve_schulstufe(_node("x", ["kompetenz"]), _lehrplan("Physik", "RP", []))
        self.assertEqual(stufe, ue.OHNE_STUFE)
        self.assertEqual(quelle, "nicht bestimmbar")

    def test_primary_grades_map_to_primarstufe(self):
        node = _node("x", ["kompetenz"], {"jahrgangsstufe": [{"uri": "https://j/3", "label": "Klassenstufe 3"}]})
        self.assertEqual(ue.resolve_schulstufe(node, _lehrplan("Sachunterricht", "SN", []))[0], ue.PRIMAR)


class KlassenstufeTest(unittest.TestCase):
    def test_node_level_is_used(self):
        name, quelle = ue.resolve_klassenstufe(_node("x", ["kompetenz"], JGS_7), _lehrplan("Gymnasium Physik", "SN", []))
        self.assertEqual(name, "Klassenstufe 7")
        self.assertEqual(quelle, "Daten (Knoten)")

    def test_range_from_title(self):
        name, quelle = ue.resolve_klassenstufe(_node("x", ["kompetenz"]), _lehrplan("Physik 7-9/10", "RP", []))
        self.assertEqual(name, "Klassenstufen 7\u201310")
        self.assertEqual(quelle, "abgeleitet aus Lehrplantitel")

    def test_unresolvable(self):
        self.assertEqual(
            ue.resolve_klassenstufe(_node("x", ["kompetenz"]), _lehrplan("Physik", "RP", []))[0], ue.OHNE_KLASSE
        )

    def test_sort_order_is_numeric_with_unknown_last(self):
        names = ["Klassenstufe 10", "Klassenstufe 7", ue.OHNE_KLASSE, "Klassenstufen 5\u20136"]
        self.assertEqual(
            sorted(names, key=ue.sort_key_klassenstufe),
            ["Klassenstufen 5\u20136", "Klassenstufe 7", "Klassenstufe 10", ue.OHNE_KLASSE],
        )


class TreeAndRenderTest(unittest.TestCase):
    def setUp(self):
        self.tree, self.stats = ue.build_tree(RESULT, include_noise=False)
        self.text = ue.render(RESULT, self.tree, self.stats, include_noise=False)

    def test_noise_is_excluded_by_default(self):
        self.assertEqual(self.stats["ausgeschlossen"], 1)
        self.assertEqual(self.stats["aufgenommen"], 5)
        self.assertNotIn("Wahlpflichtlernbereich", self.text)

    def test_noise_can_be_included(self):
        tree, stats = ue.build_tree(RESULT, include_noise=True)
        self.assertEqual(stats["ausgeschlossen"], 0)
        self.assertIn("Wahlpflichtlernbereich", ue.render(RESULT, tree, stats, include_noise=True))

    def test_levels_are_used_as_top_grouping(self):
        self.assertIn(ue.SEK_I, self.tree)
        self.assertIn(ue.SEK_II, self.tree)
        self.assertIn(ue.PRIMAR, self.tree)

    def test_grundschule_sachunterricht_appears_in_primarstufe_section(self):
        laender = self.tree[ue.PRIMAR]
        self.assertIn("Rheinland-Pfalz", laender)
        self.assertIn("Licht und Schatten", self.text)

    def test_sek_ii_section_holds_the_oberstufe_curriculum(self):
        laender = self.tree[ue.SEK_II]
        self.assertIn("Rheinland-Pfalz", laender)

    def test_headings_are_nested_in_the_requested_order(self):
        stufe_pos = self.text.index(f"## {ue.SEK_I}")
        land_pos = self.text.index("### Sachsen")
        klasse_pos = self.text.index("#### Klassenstufe 7")
        self.assertLess(stufe_pos, land_pos)
        self.assertLess(land_pos, klasse_pos)

    def test_topic_area_is_a_header_not_a_bullet(self):
        self.assertIn("**Lernbereich 2: Optik**", self.text)
        self.assertNotIn("- Lernbereich 2: Optik", self.text)

    def test_competency_is_listed_with_its_role(self):
        self.assertIn("- Lichtbrechung an Linsen", self.text)
        self.assertIn("*Kompetenz + Inhalt*", self.text)

    def test_document_reports_its_own_data_provenance(self):
        self.assertIn("## Datenlage", self.text)
        self.assertIn("abgeleitet aus Lehrplantitel", self.text)


if __name__ == "__main__":
    unittest.main()
