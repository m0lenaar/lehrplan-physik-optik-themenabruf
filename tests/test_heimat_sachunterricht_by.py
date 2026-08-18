"""Tests for the Heimat- und Sachunterricht (Bayern) rendering script.

The tree-building and role-classification require an endpoint, so these tests
cover the pure grouping and rendering logic with a small synthetic curriculum.
The fixture mirrors the Bavarian model: a Lehrplan with two levels of
Lernbereiche (both with the ``themenbereich`` role) above leaf
Kompetenzerwartungen (``kompetenz``) and Inhalte (``inhalt``).
"""

import unittest

import heimat_sachunterricht_by as hb

LP = "https://lp-bavaria.org/lis_live_isb.c.1.de"
TOP = "https://lp-bavaria.org/bereich-natur"
SUB = "https://lp-bavaria.org/bereich-tierwelt"


def _node(uri, label, rollen, eltern_uri=None):
    return {"uri": uri, "label": label, "rollen": rollen, "eltern_uri": eltern_uri}


def _fixture():
    return [
        _node(TOP, "Natur und Umwelt", ["themenbereich"], LP),
        _node(SUB, "Tiere, Pflanzen, Lebensräume", ["themenbereich"], TOP),
        _node("https://lp-bavaria.org/k1", "beschreiben Merkmale von Tieren", ["kompetenz"], SUB),
        _node("https://lp-bavaria.org/i1", "Lebensräume (z. B. Wald, Wiese)", ["inhalt"], SUB),
    ]


class BuildSectionsTest(unittest.TestCase):
    def setUp(self):
        self.sections = hb.build_sections(_fixture(), LP)

    def test_one_top_level_bereich(self):
        self.assertEqual(len(self.sections), 1)
        self.assertEqual(self.sections[0][0]["label"], "Natur und Umwelt")

    def test_sub_bereich_holds_both_leaf_roles(self):
        top, subs = self.sections[0]
        self.assertEqual(len(subs), 1)
        sub, leaves = subs[0]
        self.assertEqual(sub["label"], "Tiere, Pflanzen, Lebensräume")
        self.assertEqual(len(leaves), 2)
        roles = sorted(leaf["rollen"][0] for leaf in leaves)
        self.assertEqual(roles, ["inhalt", "kompetenz"])


class RoleMarkerTest(unittest.TestCase):
    def test_kompetenz_maps_to_kompetenzerwartung(self):
        node = _node("u", "x", ["kompetenz"])
        self.assertEqual(hb._role_marker(node), "Kompetenzerwartung")

    def test_inhalt_maps_to_inhalt(self):
        node = _node("u", "x", ["inhalt"])
        self.assertEqual(hb._role_marker(node), "Inhalt")

    def test_both_roles_join(self):
        node = _node("u", "x", ["inhalt", "kompetenz"])
        self.assertEqual(hb._role_marker(node), "Kompetenzerwartung + Inhalt")


class RenderTest(unittest.TestCase):
    def setUp(self):
        lehrplan = {
            "lehrplaene": [
                {
                    "uri": LP,
                    "label": "Heimat- und Sachunterricht 1/2",
                    "schulfach": [{"uri": "x", "label": "Heimat- und Sachunterricht"}],
                    "bundesland": [{"uri": "x", "label": "Bayern"}],
                    "schulart": [{"uri": "x", "label": "Grundschule"}],
                    "jahrgangsstufe": [{"uri": "x", "label": "Jahrgangsstufe 1"}],
                    "treffer": _fixture(),
                }
            ]
        }
        self.text = hb.render(lehrplan)

    def test_header_and_lehrplan_section(self):
        self.assertIn("# Heimat- und Sachunterricht (Grundschule, Bayern)", self.text)
        self.assertIn("## Heimat- und Sachunterricht 1/2", self.text)

    def test_metadata_lines_are_listed(self):
        self.assertIn("- Bundesland: Bayern", self.text)
        self.assertIn("- Schulart: Grundschule", self.text)
        self.assertIn("- Jahrgangsstufen: Jahrgangsstufe 1", self.text)

    def test_bereiche_and_leaves_are_nested(self):
        self.assertIn("### Natur und Umwelt", self.text)
        self.assertIn("#### Tiere, Pflanzen, Lebensräume", self.text)
        self.assertIn("- beschreiben Merkmale von Tieren", self.text)

    def test_leaves_carry_role_marker(self):
        self.assertIn("*Kompetenzerwartung*", self.text)
        self.assertIn("*Inhalt*", self.text)


if __name__ == "__main__":
    unittest.main()
