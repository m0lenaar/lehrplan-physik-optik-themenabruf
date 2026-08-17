import unittest

from mem_lehrplan import queries
from mem_lehrplan.queries import ValidationError


class ValidationTest(unittest.TestCase):
    def test_uri_must_be_http(self):
        for bad in ["", "ftp://example.org/x", "urn:x", "javascript:alert(1)"]:
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                queries.validate_uri(bad)

    def test_uri_rejects_sparql_breakout_characters(self):
        for bad in [
            "https://x.org/a b",
            'https://x.org/a"b',
            "https://x.org/a>b",
            "https://x.org/a}b",
        ]:
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                queries.validate_uri(bad)

    def test_uri_accepts_real_node_uri(self):
        self.assertEqual(
            queries.validate_uri("https://lp-sachsen.org/resource/7052"),
            "https://lp-sachsen.org/resource/7052",
        )

    def test_keyword_allows_german_curriculum_wording(self):
        for good in ["Optik", "Licht und Sehen", "Größen-Messung", "Jahrgangsstufe 7"]:
            with self.subTest(good=good):
                self.assertEqual(queries.validate_keyword(good), good)

    def test_keyword_rejects_regex_and_quote_breakout(self):
        for bad in ['Optik") } #', "Optik|(?:", "Optik\\", ""]:
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                queries.validate_keyword(bad)


class LehrplanQueryTest(unittest.TestCase):
    def test_walks_subclasses_because_endpoint_has_no_reasoning(self):
        query = queries.lehrplaene("Physik")
        self.assertIn("BIND(lp:LP_0000438 AS ?lpClass)", query)
        self.assertIn("?lpClass rdfs:subClassOf lp:LP_0000438", query)
        self.assertIn("?lpClass rdfs:subClassOf/rdfs:subClassOf lp:LP_0000438", query)

    def test_subject_keyword_is_lowercased_for_case_insensitive_contains(self):
        self.assertIn('LCASE(STR(?fachLabel)), "physik"', queries.lehrplaene("Physik"))

    def test_bundesland_filter_is_optional(self):
        self.assertNotIn("LP_0000029", queries.lehrplaene("Physik"))
        self.assertIn("LP_0000029", queries.lehrplaene("Physik", "Sachsen"))

    def test_limit_is_coerced_to_int(self):
        self.assertIn("LIMIT 5", queries.lehrplaene("Physik", limit=5))

    def test_all_lehrplaene_walks_subclasses_without_subject_filter(self):
        query = queries.alle_lehrplaene()
        self.assertIn("BIND(lp:LP_0000438 AS ?lpClass)", query)
        self.assertIn("?lpClass rdfs:subClassOf lp:LP_0000438", query)
        self.assertNotIn("?fach rdfs:label ?fachLabel", query)

    def test_all_lehrplaene_can_filter_by_bundesland(self):
        self.assertNotIn("LP_0000029", queries.alle_lehrplaene())
        self.assertIn("LP_0000029", queries.alle_lehrplaene("Sachsen"))


class NodeQueryTest(unittest.TestCase):
    def test_single_has_part_hop_and_keyword_alternation(self):
        query = queries.matching_nodes("https://lp-sachsen.org/resource/522", ["Optik", "Linse"])
        self.assertIn("<https://lp-sachsen.org/resource/522> obo:BFO_0000051 ?node", query)
        self.assertIn('"Optik|Linse", "i"', query)

    def test_label_filter_does_not_require_language_tag(self):
        query = queries.matching_nodes("https://lp-sachsen.org/resource/522", ["Optik"])
        self.assertNotIn('LANG(?nodeLabel) = "de"', query)

    def test_empty_keyword_list_is_rejected(self):
        with self.assertRaises(ValidationError):
            queries.matching_nodes("https://lp-sachsen.org/resource/522", [])

    def test_parents_query_filters_transitive_over_assertion(self):
        query = queries.direct_parents(["https://lp-sachsen.org/resource/7052"])
        self.assertIn("FILTER NOT EXISTS", query)
        self.assertIn("?mid != ?node && ?mid != ?parent", query)


class AttributeQueryTest(unittest.TestCase):
    def test_all_eight_descriptive_properties_are_named_explicitly(self):
        query = queries.descriptive_attributes(["https://lp-sachsen.org/resource/522"])
        for pid in (
            "LP_0000029",  # Bundesland
            "LP_0000537",  # Schulfach
            "LP_0000812",  # Schulart
            "LP_0000026",  # Jahrgangsstufe
            "LP_0000047",  # Schulstufe
            "LP_0000578",  # Niveaustufe
            "LP_0000833",  # Bildungsgangniveau
            "LP_0000840",  # Niveau
        ):
            with self.subTest(pid=pid):
                self.assertIn(f"lp:{pid}", query)

    def test_generic_super_property_is_queried_as_well(self):
        # The state graphs assert LP_0000024 directly instead of the specific
        # sub-property (confirmed by the predicate audit on the Berlin
        # Lehrplan), so both encodings must be fetched. The object's rdf:type
        # then decides which bucket the statement belongs to.
        query = queries.descriptive_attributes(["https://x.org/a"])
        self.assertIn("lp:LP_0000024", query)
        self.assertIn("OPTIONAL { ?o rdf:type ?oType }", query)

    def test_type_roots_resolves_level_classes_with_bounded_paths(self):
        query = queries.type_roots(["https://w3id.org/lehrplan/ontology/LP_0000450"])
        for pid in ("LP_0000009", "LP_0000020", "LP_0000443"):
            with self.subTest(pid=pid):
                self.assertIn(f"lp:{pid}", query)
        self.assertIn("?type rdfs:subClassOf ?root", query)

    def test_class_roles_covers_both_encodings(self):
        query = queries.class_roles(["https://w3id.org/lehrplan/ontology/LP_0002049"])
        self.assertIn("owl:intersectionOf ?list", query)
        self.assertIn("?list rdf:rest/rdf:first ?restriction", query)
        self.assertIn("owl:onProperty lp:LP_0000483", query)
        self.assertIn("?type rdfs:subClassOf ?ceSuper", query)


class NoTransitivePathTest(unittest.TestCase):
    """Regression guard.

    An unbound transitive path joined against the instance data makes Virtuoso
    fail with "Exceeded 1000000000 bytes in transitive temp memory" (HTTP 500).
    Every closure in this project is expressed as a bounded UNION instead, and
    no template may reintroduce ``*`` or ``+``.
    """

    ALL = {
        "alle_lehrplaene": queries.alle_lehrplaene("Sachsen", limit=5),
        "lehrplaene": queries.lehrplaene("Physik", "Sachsen", limit=5),
        "descriptive_attributes": queries.descriptive_attributes(["https://x.org/a"]),
        "matching_nodes": queries.matching_nodes("https://x.org/a", ["Optik"]),
        "direct_parents": queries.direct_parents(["https://x.org/a"]),
        "class_roles": queries.class_roles(["https://x.org/a"]),
        "predicate_audit": queries.predicate_audit(["https://x.org/a"]),
        "schulfaecher": queries.schulfaecher("Sachsen"),
        "type_roots": queries.type_roots(["https://x.org/a"]),
    }

    def test_no_query_uses_a_transitive_path_operator(self):
        for name, query in self.ALL.items():
            with self.subTest(query=name):
                self.assertNotRegex(query, r"(?:rdfs:subClassOf|rdf:rest|obo:BFO_0000051)\s*[*+]")


if __name__ == "__main__":
    unittest.main()
