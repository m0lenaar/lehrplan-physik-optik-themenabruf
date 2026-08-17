"""SPARQL query builders.

Pure string construction, no I/O -- which makes every query in this module
unit-testable without an endpoint.

All user-supplied values pass through :func:`validate_uri` or
:func:`validate_keyword` before interpolation. SPARQL has no prepared
statements, so validation is the only injection barrier available.
"""

from __future__ import annotations

import re
from typing import Sequence

from .vocab import (
    CE_SUPERCLASSES,
    CLASS_LEHRPLAN,
    DESCRIPTIVE_PROPERTIES,
    HAS_PART,
    MAX_TYPE_ROOT_DEPTH,
    PROP_BESCHRIEBEN_VON,
    TYPE_ROOTS,
    MAX_CE_SUBCLASS_DEPTH,
    MAX_INTERSECTION_LIST_LENGTH,
    MAX_LEHRPLAN_SUBCLASS_DEPTH,
    PREFIXES,
    PROP_FUNKTION,
)

_URI_FORBIDDEN = re.compile(r'[<>"\\\s{}]')
# Letters (incl. umlauts), digits, spaces and hyphens are enough for curriculum
# wording; everything else could break out of the REGEX string literal.
_KEYWORD_ALLOWED = re.compile(r"^[\wÄÖÜäöüß .\-]+$")


class ValidationError(ValueError):
    """Raised when an argument cannot be safely interpolated into SPARQL."""


def validate_uri(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValidationError("URI must be a non-empty string")
    if _URI_FORBIDDEN.search(value):
        raise ValidationError(f"URI contains forbidden characters: {value!r}")
    if not value.startswith(("http://", "https://")):
        raise ValidationError(f"URI must be http(s): {value!r}")
    return value


def validate_keyword(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError("keyword must be a non-empty string")
    if not _KEYWORD_ALLOWED.match(value):
        raise ValidationError(f"keyword contains forbidden characters: {value!r}")
    return value.strip()


def _values_block(variable: str, uris: Sequence[str]) -> str:
    joined = " ".join(f"<{validate_uri(uri)}>" for uri in uris)
    return f"VALUES ?{variable} {{ {joined} }}"


def _union(branches: list[str], indent: str = "  ") -> str:
    return f"\n{indent}UNION ".join(branches)


def _subclasses_of_constant(variable: str, root: str, max_depth: int) -> str:
    """Bind ``variable`` to ``root`` and its sub-classes down to ``max_depth``.

    Replaces ``?v rdfs:subClassOf* <root>``. The transitive form makes Virtuoso
    exhaust its transitive temp memory once it is joined against the instance
    data; fixed-length paths do not use the transitive engine at all. The depth
    zero branch binds a constant, which is valid inside a UNION branch (unlike a
    filter referencing an outside variable).
    """
    branches = [f"{{ BIND({root} AS ?{variable}) }}"]
    for depth in range(1, max_depth + 1):
        path = "/".join(["rdfs:subClassOf"] * depth)
        branches.append(f"{{ ?{variable} {path} {root} }}")
    return _union(branches)


def _subclass_reaches_variable(subject_var: str, object_var: str, max_depth: int, indent: str) -> str:
    """Sub-class paths of length 1..max_depth between two variables.

    Depth zero (``?subject`` *is* the target class) cannot be expressed here for
    the same scoping reason and is handled in :mod:`classify` instead.
    """
    branches = [
        f'{{ ?{subject_var} {"/".join(["rdfs:subClassOf"] * depth)} ?{object_var} }}'
        for depth in range(1, max_depth + 1)
    ]
    return _union(branches, indent)


def _list_members(list_var: str, member_var: str, max_length: int, indent: str) -> str:
    """Members of an RDF collection without the transitive ``rdf:rest*`` path."""
    branches = []
    for position in range(max_length):
        rests = "/".join(["rdf:rest"] * position)
        path = f"{rests}/rdf:first" if rests else "rdf:first"
        branches.append(f"{{ ?{list_var} {path} ?{member_var} }}")
    return _union(branches, indent)


def _label_option(subject_var: str, label_var: str) -> str:
    # State-graph labels are largely untagged, so accepting "" alongside "de"
    # is required -- FILTER(lang(?l) = "de") would drop most node labels.
    return (
        f"OPTIONAL {{ ?{subject_var} rdfs:label ?{label_var} "
        f'FILTER(LANG(?{label_var}) IN ("de", "")) }}'
    )


def lehrplaene(fach_keyword: str, bundesland_keyword: str | None = None, limit: int | None = None) -> str:
    """Curricula whose Schulfach label contains ``fach_keyword``.

    Walking down from LP_0000438 is load-bearing: individual Lehrpläne declare
    state sub-classes, and the endpoint does no reasoning. The walk is bounded
    rather than transitive -- see :func:`_subclasses_of_constant`.
    """
    fach = validate_keyword(fach_keyword).lower()
    clauses = [
        _subclasses_of_constant("lpClass", CLASS_LEHRPLAN, MAX_LEHRPLAN_SUBCLASS_DEPTH),
        "?lp rdf:type ?lpClass ;",
        "    rdfs:label ?lpLabel ;",
        f"    lp:{DESCRIPTIVE_PROPERTIES['schulfach']} ?fach .",
        "?fach rdfs:label ?fachLabel .",
        f'FILTER(CONTAINS(LCASE(STR(?fachLabel)), "{fach}"))',
        'FILTER(LANG(?lpLabel) IN ("de", ""))',
    ]
    if bundesland_keyword:
        land = validate_keyword(bundesland_keyword).lower()
        clauses += [
            f"?lp lp:{DESCRIPTIVE_PROPERTIES['bundesland']} ?bl .",
            "?bl rdfs:label ?blLabel .",
            f'FILTER(CONTAINS(LCASE(STR(?blLabel)), "{land}"))',
        ]
    body = "\n  ".join(clauses)
    tail = f"\nLIMIT {int(limit)}" if limit else ""
    return f"""{PREFIXES}

SELECT DISTINCT ?lp ?lpLabel
WHERE {{
  {body}
}}
ORDER BY ?lpLabel{tail}"""


def alle_lehrplaene(bundesland_keyword: str | None = None, limit: int | None = None) -> str:
    """All curricula, optionally filtered by Bundesland.

    Uses the same bounded walk from LP_0000438 as :func:`lehrplaene`, because
    the endpoint does not infer membership in the abstract Lehrplan class.
    """
    clauses = [
        _subclasses_of_constant("lpClass", CLASS_LEHRPLAN, MAX_LEHRPLAN_SUBCLASS_DEPTH),
        "?lp rdf:type ?lpClass ;",
        "    rdfs:label ?lpLabel .",
        'FILTER(LANG(?lpLabel) IN ("de", ""))',
    ]
    if bundesland_keyword:
        land = validate_keyword(bundesland_keyword).lower()
        clauses += [
            f"?lp lp:{DESCRIPTIVE_PROPERTIES['bundesland']} ?bl .",
            "?bl rdfs:label ?blLabel .",
            f'FILTER(CONTAINS(LCASE(STR(?blLabel)), "{land}"))',
        ]
    body = "\n  ".join(clauses)
    tail = f"\nLIMIT {int(limit)}" if limit else ""
    return f"""{PREFIXES}

SELECT DISTINCT ?lp ?lpLabel
WHERE {{
  {body}
}}
ORDER BY ?lpLabel{tail}"""


def descriptive_attributes(subject_uris: Sequence[str]) -> str:
    """Context and level attributes for any set of resources.

    Works for Lehrpläne and for tree nodes alike -- both carry the same
    descriptive properties -- which is why the node level lookup reuses this
    builder instead of duplicating it.
    """
    pids = list(DESCRIPTIVE_PROPERTIES.values()) + [PROP_BESCHRIEBEN_VON]
    properties = " ".join(f"lp:{pid}" for pid in pids)
    return f"""{PREFIXES}

SELECT DISTINCT ?s ?p ?o ?oLabel ?oType
WHERE {{
  {_values_block("s", subject_uris)}
  VALUES ?p {{ {properties} }}
  ?s ?p ?o .
  {_label_option("o", "oLabel")}
  OPTIONAL {{ ?o rdf:type ?oType }}
}}"""


def matching_nodes(lehrplan_uri: str, keywords: Sequence[str]) -> str:
    """Descendants of one Lehrplan whose label matches any keyword.

    A single ``obo:BFO_0000051`` hop suffices: the state graphs over-assert the
    relation transitively, so every descendant is a direct has-part of the
    Lehrplan. That is a defect for tree rendering but exactly what a flat topic
    harvest needs.
    """
    if not keywords:
        raise ValidationError("at least one keyword is required")
    alternation = "|".join(validate_keyword(word) for word in keywords)
    return f"""{PREFIXES}

SELECT DISTINCT ?node ?nodeLabel ?type
WHERE {{
  <{validate_uri(lehrplan_uri)}> {HAS_PART} ?node .
  ?node rdfs:label ?nodeLabel .
  OPTIONAL {{ ?node rdf:type ?type }}
  FILTER(REGEX(STR(?nodeLabel), "{alternation}", "i"))
}}
ORDER BY ?nodeLabel"""


def direct_parents(node_uris: Sequence[str]) -> str:
    """Truly direct parents of the given nodes.

    Without the FILTER NOT EXISTS every ancestor up to the Lehrplan would be
    reported as a parent, because of the same transitive over-assertion.
    """
    return f"""{PREFIXES}

SELECT DISTINCT ?node ?parent ?parentLabel
WHERE {{
  {_values_block("node", node_uris)}
  ?parent {HAS_PART} ?node .
  ?parent rdfs:label ?parentLabel .
  FILTER NOT EXISTS {{
    ?parent {HAS_PART} ?mid .
    ?mid {HAS_PART} ?node .
    FILTER(?mid != ?node && ?mid != ?parent)
  }}
}}"""


def class_roles(type_uris: Sequence[str]) -> str:
    """Label, function specification and CE super-class of node classes.

    Two paths are needed because the ontology encodes the didactic role in two
    ways: CE-Bereich sub-classes use a plain ``rdfs:subClassOf`` chain, while
    competency and content classes are sub-classes of an anonymous
    intersection that pins LP_0000483 to a function individual.
    """
    ce_values = " ".join(CE_SUPERCLASSES)
    return f"""{PREFIXES}

SELECT DISTINCT ?type ?typeLabel ?funktion ?ceSuper
WHERE {{
  {_values_block("type", type_uris)}
  {_label_option("type", "typeLabel")}
  OPTIONAL {{
    ?type rdfs:subClassOf ?intersection .
    ?intersection owl:intersectionOf ?list .
    {_list_members("list", "restriction", MAX_INTERSECTION_LIST_LENGTH, "    ")}
    ?restriction owl:onProperty {PROP_FUNKTION} ;
                 owl:hasValue ?funktion .
  }}
  OPTIONAL {{
    VALUES ?ceSuper {{ {ce_values} }}
    {_subclass_reaches_variable("type", "ceSuper", MAX_CE_SUBCLASS_DEPTH, "    ")}
  }}
}}"""


def type_roots(type_uris: Sequence[str]) -> str:
    """Map classes to the known root class they descend from.

    Needed because objects of the generic ``LP_0000024`` are only recognisable
    by their own ``rdf:type``, and some of those types are sub-classes (Niveau
    reaches depth 4). Depth zero -- the type *is* a root -- is resolved in
    :mod:`fetch` without a query.
    """
    roots = " ".join(f"lp:{pid}" for pid in TYPE_ROOTS.values())
    return f"""{PREFIXES}

SELECT DISTINCT ?type ?root
WHERE {{
  {_values_block("type", type_uris)}
  VALUES ?root {{ {roots} }}
  {_subclass_reaches_variable("type", "root", MAX_TYPE_ROOT_DEPTH, "  ")}
}}"""


def predicate_audit(subject_uris: Sequence[str]) -> str:
    """All predicates actually used on the given resources.

    Diagnostic only: it surfaces descriptive properties that this tool does not
    yet map, so a missing Bildungsstufe variant becomes visible instead of
    silently absent.
    """
    return f"""{PREFIXES}

SELECT DISTINCT ?p ?pLabel
WHERE {{
  {_values_block("s", subject_uris)}
  ?s ?p ?o .
  {_label_option("p", "pLabel")}
}}
ORDER BY ?p"""


def schulfaecher(bundesland_keyword: str | None = None) -> str:
    """All Schulfach labels that occur on Lehrpläne.

    Verification affordance: integrated subjects ("Natur und Technik",
    "Mensch-Natur-Technik") carry physics content but do not match the
    keyword "physik".
    """
    clauses = [f"?lp lp:{DESCRIPTIVE_PROPERTIES['schulfach']} ?fach .", "?fach rdfs:label ?fachLabel ."]
    if bundesland_keyword:
        land = validate_keyword(bundesland_keyword).lower()
        clauses += [
            f"?lp lp:{DESCRIPTIVE_PROPERTIES['bundesland']} ?bl .",
            "?bl rdfs:label ?blLabel .",
            f'FILTER(CONTAINS(LCASE(STR(?blLabel)), "{land}"))',
        ]
    body = "\n  ".join(clauses)
    return f"""{PREFIXES}

SELECT DISTINCT ?fach ?fachLabel
WHERE {{
  {body}
  FILTER(LANG(?fachLabel) IN ("de", ""))
}}
ORDER BY ?fachLabel"""
