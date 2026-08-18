#!/usr/bin/env python3
"""Render the Rheinland-Pfalz Sachunterricht curriculum as human-readable Markdown.

The script reads the MEM triplestore and prints the whole Grundschule
Sachunterricht curriculum (without any topic filter -- unlike the physics/optics
harvest) as a nested document:

    Lehrplan (Sachunterricht 1-4, Grundschule, Rheinland-Pfalz)
      Perspektive / Erfahrungsbereich   (z. B. "Perspektive Natur")
        Kompetenzbereich (RP)           (Bereich mit eigenem Titel)
          - Kompetenz (RP)              (einzelner Lerninhalt / eine Kompetenz)

The RP curriculum is three levels deep: Perspektiven are not asserted as their
own nodes but appear as the first line of every Kompetenzbereich label, so a
Kompetenzbereich label reads "Perspektive Natur\\nNaturphänomene ... erforschen".
Grouping by that first line reconstructs the Perspektiven the data implies.

    python3 sachunterricht_rp.py
    python3 sachunterricht_rp.py -o sachunterricht_rp.md
    python3 sachunterricht_rp.py --bundesland "Rheinland-Pfalz"

Standalone by design: it reuses the query/builders from the ``mem_lehrplan``
package (same standard-library-only dependency as the rest of the repository).
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from collections import defaultdict
from pathlib import Path

from mem_lehrplan.classify import build_class_index, node_roles
from mem_lehrplan.fetch import fetch_attributes
from mem_lehrplan.queries import ValidationError, class_roles, direct_parents, lehrplaene
from mem_lehrplan.sparql import SparqlClient, SparqlError, collect_labelled
from mem_lehrplan.vocab import DEFAULT_ENDPOINT

logger = logging.getLogger(__name__)

FACH = "sachunterricht"
BUNDESLAND = "Rheinland-Pfalz"

# Whether a node is a leaf (Kompetenz) or an inner Kompetenzbereich is decided by
# its didactic role: inner nodes carry the "themenbereich" role, everything else
# is listed as a competency/content bullet.
ROLE_BEREICH = "themenbereich"


def _labels(entries: list[dict[str, str]]) -> list[str]:
    return [entry.get("label") or entry["uri"] for entry in entries]


def _roles_for_nodes(client: SparqlClient, nodes: dict[str, dict]) -> dict[str, list[str]]:
    """Map every tree node URI to its list of didactic roles.

    Reuses the same ontology walk (LP_0000483 function specification + CE
    super-class chain) as the physics harvest, so a node read as "themenbereich"
    is a Kompetenzbereich and a node read as "kompetenz"/"inhalt" is listed as a
    leaf competency.
    """
    type_uris = sorted({t for node in nodes.values() for t in node["typen"]})
    if not type_uris:
        return {}
    index = build_class_index(client.select(class_roles(type_uris)))
    return {uri: node_roles(node["typen"], index) for uri, node in nodes.items()}


def _single_parent(parent_rows: list[dict[str, str]]) -> dict[str, str]:
    """Map every node URI to its single direct parent URI.

    Uses the first real parent found. In practice each node sits under exactly
    one Kompetenzbereich; the dict keeps the relation deterministic either way.
    """
    result: dict[str, str] = {}
    for row in parent_rows:
        node = row.get("node")
        parent = row.get("parent")
        if node and parent and node not in result:
            result[node] = parent
    return result


def build_tree(client: SparqlClient, lehrplan_uri: str) -> list[dict]:
    """Fetch the full curriculum of one Lehrplan.

    ``obo:BFO_0000051`` is transitively over-asserted in the state graphs, so one
    hop from the Lehrplan already yields every descendant. Each node carries its
    didactic role and the URI of its *direct* parent, which lets the renderer
    reconstruct the Perspektive -> Kompetenzbereich -> Kompetenz nesting without
    assuming any particular storage order.
    """
    descendant_rows = client.select(_descendants_query(lehrplan_uri))
    nodes: dict[str, dict] = {}
    for row in descendant_rows:
        node = nodes.setdefault(row["node"], {"uri": row["node"], "label": row.get("nodeLabel", ""), "typen": []})
        if row.get("type") and row["type"] not in node["typen"]:
            node["typen"].append(row["type"])

    roles = _roles_for_nodes(client, nodes)
    for uri, node in nodes.items():
        node["rollen"] = roles.get(uri, [])

    parent_rows = client.select(direct_parents(list(nodes)))
    parents = _single_parent(parent_rows)

    treffer = []
    for uri in nodes:
        node = nodes[uri]
        treffer.append(
            {
                "uri": uri,
                "label": node["label"],
                "rollen": node["rollen"],
                "eltern_uri": parents.get(uri),
            }
        )
    return treffer


def _descendants_query(lehrplan_uri: str) -> str:
    """SPARQL for every descendant of a curriculum node with label and type."""
    from mem_lehrplan import queries

    return f"""{queries.PREFIXES}

SELECT DISTINCT ?node ?nodeLabel ?type
WHERE {{
  <{lehrplan_uri}> {queries.HAS_PART} ?node .
  ?node rdfs:label ?nodeLabel .
  OPTIONAL {{ ?node rdf:type ?type }}
}}
ORDER BY ?nodeLabel"""


def _perspektive(bereich_label: str) -> tuple[str, str]:
    """Split a Kompetenzbereich label into (Perspektive, Bereichstitel).

    In the RP data the Perspektive is the first line of the Kompetenzbereich
    label, e.g. ``"Perspektive Natur\\nNaturphänomene ...\"``. A label without a
    newline is treated as its own Perspektive.
    """
    first, _, rest = bereich_label.partition("\n")
    return first.strip(), rest.strip()


def _group_by_bereich(treffer: list[dict]) -> dict[str, dict[tuple[str, str], list[dict]]]:
    """Group nodes by Perspektive, then by Kompetenzbereich.

    Inner nodes (Kompetenzbereiche, role "themenbereich") become headings;
    leaf nodes are grouped under their direct parent Kompetenzbereich.
    """
    by_uri = {node["uri"]: node for node in treffer}
    bereiche = {node["uri"]: node for node in treffer if ROLE_BEREICH in node["rollen"]}

    grouped: dict[str, dict[tuple[str, str], list[dict]]] = defaultdict(lambda: defaultdict(list))
    for node in treffer:
        parent_uri = node.get("eltern_uri")
        parent = by_uri.get(parent_uri) if parent_uri else None
        if parent and parent["uri"] in bereiche:
            perspektive, titel = _perspektive(parent["label"])
            grouped[perspektive][(parent["uri"], titel)].append(node)
        elif ROLE_BEREICH in node["rollen"]:
            # A Kompetenzbereich without children (or without a detected parent)
            # still appears under its own Perspektive.
            perspektive, titel = _perspektive(node["label"])
            grouped.setdefault(perspektive, defaultdict(list)).setdefault((node["uri"], titel), [])
    return grouped


def render(lehrplan: dict, treffer: list[dict]) -> str:
    """Render the curriculum as a human-readable Markdown document."""
    out: list[str] = []
    add = out.append

    label = lehrplan["label"]
    add(f"# {label}")
    add("")
    add("Rahmenplan Grundschule – Teilrahmenplan Sachunterricht des Landes")
    add("Rheinland-Pfalz, aus dem MEM-Triplestore ausgelesen und hier in")
    add("lesbarer Form dargestellt.")
    add("")
    add(f"- Fach: {', '.join(_labels(lehrplan.get('schulfach', []))) or 'Sachunterricht'}")
    add(f"- Bundesland: {', '.join(_labels(lehrplan.get('bundesland', []))) or 'Rheinland-Pfalz'}")
    add(f"- Schulart: {', '.join(_labels(lehrplan.get('schulart', []))) or 'Grundschule'}")
    jgs = _labels(lehrplan.get("jahrgangsstufe", []))
    if jgs:
        add(f"- Jahrgangsstufen: {', '.join(jgs)}")
    add("")
    add("Der Lehrplan ist nach Perspektiven bzw. Erfahrungsbereichen gegliedert;")
    add("unter jeder Perspektive stehen die Kompetenzbereiche und darunter die")
    add("einzelnen Kompetenzen.")
    add("")

    grouped = _group_by_bereich(treffer)

    for perspektive in sorted(grouped, key=str.casefold):
        add(f"## {perspektive}")
        add("")
        for (bereich_uri, bereichstitel), kompetenzen in sorted(
            grouped[perspektive].items(), key=lambda item: (item[0][1].casefold(), item[0][0])
        ):
            title = bereichstitel or "Kompetenzbereich"
            add(f"### {title}")
            add("")
            for node in sorted(kompetenzen, key=lambda entry: entry["label"]):
                add(f"- {node['label']}")
            add("")
    return "\n".join(out).rstrip() + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Gibt den Sachunterricht-Lehrplan von Rheinland-Pfalz als lesbares Markdown aus.",
    )
    parser.add_argument(
        "--endpoint",
        default=os.environ.get("MEM_SPARQL_ENDPOINT", DEFAULT_ENDPOINT),
        help="SPARQL-Endpoint (oder Umgebungsvariable MEM_SPARQL_ENDPOINT)",
    )
    parser.add_argument("--bundesland", default=BUNDESLAND, help="Bundesland-Stichwort (Default: Rheinland-Pfalz)")
    parser.add_argument("-o", "--out", type=Path, help="Schreibe das Markdown zusaetzlich in eine Datei")
    parser.add_argument("-v", "--verbose", action="store_true", help="Fortschritt protokollieren")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(message)s",
    )
    client = SparqlClient(args.endpoint)

    try:
        rows = client.select(lehrplaene(FACH, args.bundesland))
        lps = collect_labelled(rows, "lp", "lpLabel")
        if not lps:
            print(f"Kein Sachunterricht-Lehrplan fuer Bundesland {args.bundesland!r} gefunden.", file=sys.stderr)
            return 1
        lehrplan = lps[0]
        logger.info("Lehrplan: %s", lehrplan["label"])
        attributes = fetch_attributes(client, [lehrplan["uri"]])[lehrplan["uri"]]
        treffer = build_tree(client, lehrplan["uri"])
    except ValidationError as error:
        print(f"Ungueltige Eingabe: {error}", file=sys.stderr)
        return 2
    except SparqlError as error:
        print(f"SPARQL-Fehler: {error}", file=sys.stderr)
        return 1

    metadata = {
        "label": lehrplan["label"],
        "schulfach": attributes.get("schulfach", []),
        "bundesland": attributes.get("bundesland", []),
        "schulart": attributes.get("schulart", []),
        "jahrgangsstufe": attributes.get("jahrgangsstufe", []),
    }
    output = render(metadata, treffer)
    print(output, end="")
    if args.out:
        args.out.write_text(output, encoding="utf-8")
        print(f"\n-> {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
