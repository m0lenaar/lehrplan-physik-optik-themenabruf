"""Assembly tests against a fake client.

No network: the fake dispatches on markers unique to each query template and
returns bindings shaped like Virtuoso's SPARQL-JSON (already flattened by
SparqlClient.select).
"""

import unittest

from mem_lehrplan.export import flatten
from mem_lehrplan.fetch import harvest

ONTO = "https://w3id.org/lehrplan/ontology/"
LP = "https://lp-sachsen.org/resource/522"
BEREICH = "https://lp-sachsen.org/resource/7052"
KOMPETENZ = "https://lp-sachsen.org/resource/7053"

JGS_7 = ONTO + "LP_1000007"
SEK_I = ONTO + "LP_0000018"


class FakeClient:
    """Returns canned rows and records every query it received."""

    endpoint = "http://fake/sparql"

    def __init__(self):
        self.queries = []

    def select(self, query):
        self.queries.append(query)
        if "owl:onProperty" in query:
            return [
                {"type": ONTO + "LP_0002113", "typeLabel": "Lernbereich (SN)", "ceSuper": ONTO + "LP_0000349"},
                {"type": ONTO + "LP_0002049", "typeLabel": "Kompetenzerwartung (BY)", "funktion": ONTO + "LP_0000479"},
            ]
        if "FILTER NOT EXISTS" in query:
            return [{"node": KOMPETENZ, "parent": BEREICH, "parentLabel": "Lernbereich 2: Optik"}]
        if "FILTER(REGEX" in query:
            return [
                {"node": BEREICH, "nodeLabel": "Lernbereich 2: Optik", "type": ONTO + "LP_0002113"},
                {"node": KOMPETENZ, "nodeLabel": "Lichtbrechung an Linsen", "type": ONTO + "LP_0002049"},
            ]
        if "VALUES ?p" in query:
            rows = [
                {"s": LP, "p": ONTO + "LP_0000029", "o": ONTO + "LP_3000047", "oLabel": "Sachsen"},
                {"s": LP, "p": ONTO + "LP_0000537", "o": ONTO + "LP_0000600", "oLabel": "Physik"},
                {"s": LP, "p": ONTO + "LP_0000812", "o": ONTO + "LP_0000112", "oLabel": "Oberschule"},
                {"s": LP, "p": ONTO + "LP_0000047", "o": SEK_I, "oLabel": "Sekundarbereich I"},
                {"s": KOMPETENZ, "p": ONTO + "LP_0000026", "o": JGS_7, "oLabel": "Klassenstufe 7"},
            ]
            return [row for row in rows if row["s"] in query]
        if "SELECT DISTINCT ?p ?pLabel" in query:
            return [{"p": ONTO + "LP_0000029", "pLabel": "von Bundesland"}]
        if "CONTAINS(LCASE(STR(?fachLabel))" in query and "sachunterricht" in query:
            return [
                {"lp": LP, "lpLabel": "Physik Oberschule (SN)", "fachLabel": "Physik"},
                {
                    "lp": "https://lp-rp.org/resource/1",
                    "lpLabel": "Sachunterricht 1-4 (RP)",
                    "fachLabel": "Sachunterricht",
                },
            ]
        if "CONTAINS(LCASE(STR(?fachLabel))" in query:
            return [{"lp": LP, "lpLabel": "Physik Oberschule (SN)", "fachLabel": "Physik"}]
        return [{"lp": LP, "lpLabel": "Physik Oberschule (SN)", "fachLabel": "Physik"}]


class HarvestTest(unittest.TestCase):
    def setUp(self):
        self.client = FakeClient()
        self.result = harvest(self.client, fach="physik", stichwoerter=["Optik", "Licht"])
        self.lehrplan = self.result["lehrplaene"][0]
        self.by_uri = {node["uri"]: node for node in self.lehrplan["treffer"]}

    def test_counts(self):
        self.assertEqual(self.result["anzahl"], {"lehrplaene": 1, "treffer": 2})

    def test_lehrplan_context_is_resolved_to_labels(self):
        self.assertEqual(self.lehrplan["bundesland"][0]["label"], "Sachsen")
        self.assertEqual(self.lehrplan["schulart"][0]["label"], "Oberschule")

    def test_lehrplan_level_is_captured(self):
        self.assertEqual(self.lehrplan["stufen"]["schulstufe"][0]["label"], "Sekundarbereich I")

    def test_node_with_own_level_keeps_it_and_is_marked_as_such(self):
        node = self.by_uri[KOMPETENZ]
        self.assertEqual(node["stufen"]["jahrgangsstufe"][0]["label"], "Klassenstufe 7")
        self.assertEqual(node["stufen_quelle"], "knoten")

    def test_node_without_own_level_inherits_from_lehrplan(self):
        node = self.by_uri[BEREICH]
        self.assertEqual(node["stufen"]["schulstufe"][0]["label"], "Sekundarbereich I")
        self.assertEqual(node["stufen_quelle"], "lehrplan")

    def test_roles_separate_topic_area_from_competency(self):
        self.assertEqual(self.by_uri[BEREICH]["rollen"], ["themenbereich"])
        self.assertEqual(self.by_uri[KOMPETENZ]["rollen"], ["kompetenz"])

    def test_competency_is_linked_to_its_topic_area(self):
        self.assertEqual(self.by_uri[KOMPETENZ]["eltern"][0]["label"], "Lernbereich 2: Optik")

    def test_diagnostics_report_used_predicates(self):
        labels = [entry["label"] for entry in self.result["diagnostik"]["lehrplan_praedikate"]]
        self.assertIn("von Bundesland", labels)

    def test_empty_result_short_circuits_without_further_queries(self):
        class EmptyClient(FakeClient):
            def select(self, query):
                super().select(query)
                return []

        client = EmptyClient()
        result = harvest(client, fach="physik", stichwoerter=["Optik"])
        self.assertEqual(result["anzahl"]["lehrplaene"], 0)
        self.assertEqual(len(client.queries), 1)

    def test_multiple_subjects_yield_combined_curricula(self):
        result = harvest(
            self.client, fach=["physik", "sachunterricht"], stichwoerter=["Optik", "Licht"]
        )
        labels = {entry["label"] for entry in result["lehrplaene"]}
        self.assertIn("Physik Oberschule (SN)", labels)
        self.assertIn("Sachunterricht 1-4 (RP)", labels)
        self.assertEqual(result["filter"]["fach"], ["physik", "sachunterricht"])

    def test_single_string_fach_is_backwards_compatible(self):
        result = harvest(self.client, fach="physik", stichwoerter=["Optik"])
        self.assertEqual(result["filter"]["fach"], ["physik"])


class FlattenTest(unittest.TestCase):
    def test_one_row_per_node_with_levels_alongside(self):
        result = harvest(FakeClient(), fach="physik", stichwoerter=["Optik"])
        rows = flatten(result)
        self.assertEqual(len(rows), 2)
        competency = next(row for row in rows if row["knoten"] == "Lichtbrechung an Linsen")
        self.assertEqual(competency["jahrgangsstufe"], "Klassenstufe 7")
        self.assertEqual(competency["bundesland"], "Sachsen")
        self.assertEqual(competency["eltern"], "Lernbereich 2: Optik")
        self.assertEqual(competency["rollen"], "kompetenz")


if __name__ == "__main__":
    unittest.main()
