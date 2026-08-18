"""Tests for the Sachunterricht Rheinland-Pfalz rendering script.

The tests exercise the pure logic (perspective splitting, grouping by
Kompetenzbereich, rendering) with a small synthetic curriculum; no endpoint
access is required. The fixture mirrors the RP data model: inner nodes
(Kompetenzbereiche) carry the ``themenbereich`` role and a two-line label whose
first line is the Perspektive, while leaf nodes are ``kompetenz`` nodes whose
parent is that Kompetenzbereich.
"""

import unittest

import sachunterricht_rp as su


def _node(uri, label, rollen, eltern_uri=None):
    return {"uri": uri, "label": label, "rollen": rollen, "eltern_uri": eltern_uri}


# Lehrplan root is not represented as a treffer node; Kompetenzbereiche point at it.
LP = "https://lp-rlp.org/resource/lehrplan-222-1"

NATUR = "https://lp-rlp.org/resource/bereich-natur"
GESELL = "https://lp-rlp.org/resource/bereich-gesellschaft"


def _fixture():
    return [
        _node(NATUR, "Perspektive Natur\nNatürliche Phänomene beobachten", ["themenbereich"], LP),
        _node("https://lp-rlp.org/resource/komp-natur-1", "Pflanzen unterscheiden", ["kompetenz"], NATUR),
        _node("https://lp-rlp.org/resource/komp-natur-2", "Tiere beobachten", ["kompetenz"], NATUR),
        _node(GESELL, "Ich und Andere – Perspektive Gesellschaft\nSoziales Miteinander", ["themenbereich"], LP),
        _node("https://lp-rlp.org/resource/komp-ges-1", "Konflikte lösen", ["kompetenz"], GESELL),
    ]


class PerspektiveTest(unittest.TestCase):
    def test_perspektive_is_the_first_line(self):
        perspektive, titel = su._perspektive("Perspektive Natur\nNatürliche Phänomene beobachten")
        self.assertEqual(perspektive, "Perspektive Natur")
        self.assertEqual(titel, "Natürliche Phänomene beobachten")

    def test_label_without_newline_is_its_own_perspektive(self):
        self.assertEqual(su._perspektive("Nur ein Titel"), ("Nur ein Titel", ""))


class GroupByBereichTest(unittest.TestCase):
    def setUp(self):
        self.grouped = su._group_by_bereich(_fixture())

    def test_two_perspektiven_are_recognised(self):
        self.assertEqual(len(self.grouped), 2)
        self.assertIn("Perspektive Natur", self.grouped)
        self.assertIn("Ich und Andere – Perspektive Gesellschaft", self.grouped)

    def test_kompetenzen_are_grouped_under_their_parent_bereich(self):
        natur_komp = self.grouped["Perspektive Natur"][(NATUR, "Natürliche Phänomene beobachten")]
        labels = sorted(node["label"] for node in natur_komp)
        self.assertEqual(labels, ["Pflanzen unterscheiden", "Tiere beobachten"])

    def test_bereich_without_children_has_empty_heading(self):
        # A Kompetenzbereich whose children were not harvested still appears.
        treffer = [
            _node(NATUR, "Perspektive Natur\nEin Bereich", ["themenbereich"], LP),
        ]
        grouped = su._group_by_bereich(treffer)
        self.assertEqual(grouped["Perspektive Natur"][(NATUR, "Ein Bereich")], [])


class RenderTest(unittest.TestCase):
    def setUp(self):
        lehrplan = {
            "label": "Sachunterricht 1-4",
            "schulfach": [{"uri": "x", "label": "Sachunterricht"}],
            "bundesland": [{"uri": "x", "label": "Rheinland-Pfalz"}],
            "schulart": [{"uri": "x", "label": "Grundschule"}],
            "jahrgangsstufe": [
                {"uri": "x", "label": "Jahrgangsstufe 1"},
                {"uri": "x", "label": "Jahrgangsstufe 2"},
            ],
        }
        self.text = su.render(lehrplan, _fixture())

    def test_header_names_the_framework(self):
        self.assertIn("# Sachunterricht 1-4", self.text)
        self.assertIn("Rheinland-Pfalz", self.text)

    def test_metadata_lines_are_listed(self):
        self.assertIn("- Fach: Sachunterricht", self.text)
        self.assertIn("- Bundesland: Rheinland-Pfalz", self.text)
        self.assertIn("- Schulart: Grundschule", self.text)
        self.assertIn("- Jahrgangsstufen: Jahrgangsstufe 1, Jahrgangsstufe 2", self.text)

    def test_perspektiven_are_h2_headers(self):
        self.assertIn("## Perspektive Natur", self.text)
        self.assertIn("## Ich und Andere – Perspektive Gesellschaft", self.text)

    def test_bereiche_are_h3_and_kompetenzen_are_bullets(self):
        self.assertIn("### Natürliche Phänomene beobachten", self.text)
        self.assertIn("- Pflanzen unterscheiden", self.text)
        self.assertIn("- Tiere beobachten", self.text)


if __name__ == "__main__":
    unittest.main()
