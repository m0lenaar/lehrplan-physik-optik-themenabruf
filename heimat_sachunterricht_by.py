#!/usr/bin/env python3
"""Render the Bavarian Heimat- und Sachunterricht curriculum as Markdown.

Like ``sachunterricht_rp.py`` but for the Grundschule Lehrpläne of Bayern. Unlike
Rheinland-Pfalz -- which has one Sachunterricht curriculum covering grades 1-4 --
Bayern splits it into two curricula: "Heimat- und Sachunterricht 1/2" and
"Heimat- und Sachunterricht 3/4". Both are rendered, each as its own section.

The Bavarian hierarchy is one level deeper than the RP one:

    Lehrplan (Heimat- und Sachunterricht 1/2 oder 3/4)
      Lernbereich (BY)                6 geteilt über beide Lehrpläne, z. B. "Natur und Umwelt"
        Lernbereich (BY)              15 Unter-Lernbereiche, z. B. "Luft, Wasser, Wetter"
          - Kompetenzerwartung (BY)   z. B. "beschreiben das Prinzip des Kaufvorgangs ..."
          - Inhalt (BY)               z. B. "Kaufen und Verkaufen"

The didactic roles come from the same ontology walk as the physics harvest and
the RP script: ``Lernbereich (BY)`` -> themenbereich, ``Kompetenzerwartung (BY)``
-> kompetenz, ``Inhalt zu den Kompetenzen (BY)`` -> inhalt.

    python3 heimat_sachunterricht_by.py
    python3 heimat_sachunterricht_by.py -o heimat_sachunterricht_by.md
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from mem_lehrplan.fetch import fetch_attributes
from mem_lehrplan.queries import ValidationError
from mem_lehrplan.sparql import SparqlClient, SparqlError, collect_labelled
from mem_lehrplan.vocab import DEFAULT_ENDPOINT

from sachunterricht_rp import build_tree, _labels

logger = logging.getLogger(__name__)

FACH = "sachunterricht"
BUNDESLAND = "Bayern"
SCHULART = "Grundschule"

ROLE_BEREICH = "themenbereich"
ROLE_KOMPETENZ = "kompetenz"
ROLE_INHALT = "inhalt"

_ROLE_NAMES = {ROLE_KOMPETENZ: "Kompetenzerwartung", ROLE_INHALT: "Inhalt"}


def _sachunterricht_curricula_query(fach_keyword: str) -> str:
    """Find curricula by subject across all Bundesländer.

    The abstract-Lehrplan class walk used in ``queries.lehrplaene`` does not
    reach the Bayern Lehrpläne: ``Fachlehrplan (BY)`` / ``Lehrplanfragment (BY)``
    sit too deep below ``LP_0000438`` for the bounded walk. Matching the asserted
    ``LP_0000537`` (hat Schulfach) directly is faster and finds them all; the
    Bundesland and Schulart are then narrowed in Python.
    """
    from mem_lehrplan import queries

    keyword = queries.validate_keyword(fach_keyword).lower()
    return f"""{queries.PREFIXES}

SELECT DISTINCT ?lp ?lpLabel
WHERE {{
  ?lp rdfs:label ?lpLabel ;
      lp:{queries.DESCRIPTIVE_PROPERTIES['schulfach']} ?fach .
  ?fach rdfs:label ?fachLabel .
  FILTER(CONTAINS(LCASE(STR(?fachLabel)), "{keyword}"))
  FILTER(LANG(?lpLabel) IN ("de", ""))
}}
ORDER BY ?lpLabel"""


def select_grundschule(client: SparqlClient, fach: str, bundesland: str, schulart: str) -> list[dict]:
    """All Grundschule Heimat- und Sachunterricht Lehrpläne of a Bundesland.

    Starts from the label pre-filter (all Länder), then keeps only the curricula
    whose asserted Bundesland and Schulart match -- resolved through the generic
    ``LP_0000024`` encoding, which :func:`fetch_attributes` already understands.
    """
    rows = client.select(_sachunterricht_curricula_query(fach))
    candidates = collect_labelled(rows, "lp", "lpLabel")
    if not candidates:
        return []
    attrs = fetch_attributes(client, [entry["uri"] for entry in candidates])
    selected = []
    for entry in candidates:
        labels = lambda bucket: [
            str(value.get("label") or value.get("uri") or "")
            for value in attrs.get(entry["uri"], {}).get(bucket, [])
        ]
        has_land = any(bundesland.lower() in label.lower() for label in labels("bundesland"))
        has_schulart = any(schulart.lower() in label.lower() for label in labels("schulart"))
        if has_land and has_schulart:
            selected.append(entry)
    return selected


def _children(parent_uri: str, treffer: list[dict]) -> list[dict]:
    return sorted(
        (node for node in treffer if node.get("eltern_uri") == parent_uri),
        key=lambda node: (node["label"].casefold(), node["uri"]),
    )


def build_sections(treffer: list[dict], lehrplan_uri: str) -> list[tuple[dict, list[tuple[dict, list[dict]]]]]:
    """Group a Lehrplan's nodes as top Lernbereich -> (sub Lernbereich -> leaves).

    Returns, in stable order, one entry per top-level Lernbereich: its node plus
    the list of its sub-Lernbereiche, each with the leaf nodes beneath it.
    """
    sections = []
    for top in _children(lehrplan_uri, treffer):
        subs = []
        for sub in _children(top["uri"], treffer):
            leaves = _children(sub["uri"], treffer)
            if leaves or ROLE_BEREICH in sub["rollen"]:
                subs.append((sub, leaves))
        sections.append((top, subs))
    return sections


def _role_marker(node: dict) -> str:
    names = [_ROLE_NAMES[role] for role in (ROLE_KOMPETENZ, ROLE_INHALT) if role in node["rollen"]]
    return " + ".join(names) or "Themenbereich"


def render(lehrplan: dict) -> str:
    """Render the whole Bavarian Heimat- und Sachunterricht curriculum."""
    out: list[str] = []
    add = out.append

    add("# Heimat- und Sachunterricht (Grundschule, Bayern)")
    add("")
    add("Teilrahmenplan des Landes Bayern, aus dem MEM-Triplestore ausgelesen und")
    add("hier in lesbarer Form dargestellt. Das Fach ist in zwei Lehrpläne geteilt")
    add("(Jahrgangsstufen 1/2 und 3/4), die je einen eigenen Abschnitt bilden.")
    add("")

    for lp in lehrplan["lehrplaene"]:
        label = lp["label"]
        add(f"## {label}")
        add("")
        add(f"- Fach: {', '.join(_labels(lp.get('schulfach', []))) or 'Heimat- und Sachunterricht'}")
        add(f"- Bundesland: {', '.join(_labels(lp.get('bundesland', []))) or 'Bayern'}")
        add(f"- Schulart: {', '.join(_labels(lp.get('schulart', []))) or 'Grundschule'}")
        jgs = _labels(lp.get("jahrgangsstufe", []))
        if jgs:
            add(f"- Jahrgangsstufen: {', '.join(jgs)}")
        add("")

        sections = build_sections(lp["treffer"], lp["uri"])
        for top, subs in sections:
            add(f"### {top['label']}")
            add("")
            for sub, leaves in subs:
                add(f"#### {sub['label']}")
                add("")
                if not leaves:
                    add("*(keine Inhalte erfasst)*")
                    add("")
                    continue
                for leaf in leaves:
                    add(f"- {leaf['label']}  \n  *{_role_marker(leaf)}*")
                add("")
    return "\n".join(out).rstrip() + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Gibt den Heimat- und Sachunterricht-Lehrplan (Grundschule) von Bayern "
        "als lesbares Markdown aus.",
    )
    parser.add_argument(
        "--endpoint",
        default=os.environ.get("MEM_SPARQL_ENDPOINT", DEFAULT_ENDPOINT),
        help="SPARQL-Endpoint (oder Umgebungsvariable MEM_SPARQL_ENDPOINT)",
    )
    parser.add_argument("--bundesland", default=BUNDESLAND, help="Bundesland-Stichwort (Default: Bayern)")
    parser.add_argument("--schulart", default=SCHULART, help="Schulart-Filter (Default: Grundschule)")
    parser.add_argument("--fach", default=FACH, help="Stichwort im Schulfach-Label (Default: sachunterricht)")
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
        lehrplaene_list = select_grundschule(client, args.fach, args.bundesland, args.schulart)
        if not lehrplaene_list:
            print(f"Keine Heimat- und Sachunterricht-Grundschule-Lehrplaene fuer "
                  f"{args.bundesland!r} gefunden.", file=sys.stderr)
            return 1
        lehrplan_records = []
        for entry in lehrplaene_list:
            logger.info("Lehrplan: %s", entry["label"] or entry["uri"])
            attributes = fetch_attributes(client, [entry["uri"]])[entry["uri"]]
            treffer = build_tree(client, entry["uri"])
            lehrplan_records.append(
                {
                    "uri": entry["uri"],
                    "label": entry["label"] or entry["uri"],
                    "schulfach": attributes.get("schulfach", []),
                    "bundesland": attributes.get("bundesland", []),
                    "schulart": attributes.get("schulart", []),
                    "jahrgangsstufe": attributes.get("jahrgangsstufe", []),
                    "treffer": treffer,
                }
            )
    except ValidationError as error:
        print(f"Ungueltige Eingabe: {error}", file=sys.stderr)
        return 2
    except SparqlError as error:
        print(f"SPARQL-Fehler: {error}", file=sys.stderr)
        return 1

    output = render({"lehrplaene": lehrplan_records})
    print(output, end="")
    if args.out:
        args.out.write_text(output, encoding="utf-8")
        print(f"\n-> {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
