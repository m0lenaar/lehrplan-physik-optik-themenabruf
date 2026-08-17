#!/usr/bin/env python3
"""List subjects grouped by land, school form and grade information.

Example:

    python3 faecher_uebersicht.py
    python3 faecher_uebersicht.py --bundesland Sachsen --limit 50 -o faecher.txt

The script reads all curricula from the MEM triplestore, resolves their
descriptive attributes via the existing query/fetch helpers and prints a plain
text tree:

    Fach
      Land
        Schulform
          - Klassenstufe ...
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

from mem_lehrplan.fetch import fetch_attributes
from mem_lehrplan.queries import ValidationError, alle_lehrplaene
from mem_lehrplan.sparql import SparqlClient, SparqlError, collect_labelled
from mem_lehrplan.vocab import DEFAULT_ENDPOINT

logger = logging.getLogger(__name__)

OHNE_FACH = "Ohne Fach"
OHNE_LAND = "Ohne Bundesland"
OHNE_SCHULFORM = "Ohne Schulform"
OHNE_KLASSEN = "Ohne Klassenstufenangabe"
_GRADE = re.compile(r"\b(\d{1,2})\b")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Listet Faecher aus dem MEM-Triplestore nach Land, Schulform und Klassenstufen.",
    )
    parser.add_argument(
        "--endpoint",
        default=os.environ.get("MEM_SPARQL_ENDPOINT", DEFAULT_ENDPOINT),
        help="SPARQL-Endpoint (oder Umgebungsvariable MEM_SPARQL_ENDPOINT)",
    )
    parser.add_argument("--bundesland", help="Optionaler Bundesland-Filter, z. B. Sachsen")
    parser.add_argument("--limit", type=int, help="Maximale Anzahl Lehrplaene fuer einen Smoke-Test")
    parser.add_argument("-o", "--out", type=Path, help="Schreibe die Ausgabe zusaetzlich in eine Textdatei")
    parser.add_argument("-v", "--verbose", action="store_true", help="Fortschritt protokollieren")
    return parser


def _labels(entries: list[dict[str, str]]) -> list[str]:
    return [entry.get("label") or entry["uri"] for entry in entries if entry.get("label") or entry.get("uri")]


def _unique_sorted(values: list[str]) -> list[str]:
    return sorted(set(values), key=lambda value: (_grade_sort_key(value), value.casefold()))


def _grade_sort_key(label: str) -> tuple[int, str]:
    numbers = [int(match.group(1)) for match in _GRADE.finditer(label) if 1 <= int(match.group(1)) <= 13]
    return (min(numbers) if numbers else 99, label.casefold())


def _derived_grades(label: str) -> list[str]:
    grades = sorted({int(match.group(1)) for match in _GRADE.finditer(label) if 1 <= int(match.group(1)) <= 13})
    return [f"Klassenstufe {grade}" for grade in grades]


def _level_labels(lehrplan_label: str, attributes: dict[str, list[dict[str, str]]]) -> list[str]:
    jahrgangsstufen = _labels(attributes.get("jahrgangsstufe", []))
    if jahrgangsstufen:
        return _unique_sorted(jahrgangsstufen)

    derived = _derived_grades(lehrplan_label)
    if derived:
        return derived

    fallback: list[str] = []
    for bucket in ("schulstufe", "niveaustufe", "bildungsgangniveau", "niveau"):
        fallback.extend(_labels(attributes.get(bucket, [])))
    return _unique_sorted(fallback) or [OHNE_KLASSEN]


def build_tree(lehrplaene: list[dict[str, str]], attributes_by_uri: dict[str, dict[str, list[dict[str, str]]]]) -> dict:
    tree: dict[str, dict[str, dict[str, set[str]]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(set)))
    for lehrplan in lehrplaene:
        attributes = attributes_by_uri.get(lehrplan["uri"], {})
        faecher = _unique_sorted(_labels(attributes.get("schulfach", []))) or [OHNE_FACH]
        laender = _unique_sorted(_labels(attributes.get("bundesland", []))) or [OHNE_LAND]
        schulformen = _unique_sorted(_labels(attributes.get("schulart", []))) or [OHNE_SCHULFORM]
        klassen = _level_labels(lehrplan["label"], attributes)
        for fach in faecher:
            for land in laender:
                for schulform in schulformen:
                    tree[fach][land][schulform].update(klassen)
    return tree


def render(tree: dict[str, dict[str, dict[str, set[str]]]], count: int, endpoint: str, bundesland: str | None) -> str:
    lines = [
        "Faecheruebersicht aus dem MEM-Triplestore",
        f"Endpoint: {endpoint}",
        f"Lehrplaene: {count}",
    ]
    if bundesland:
        lines.append(f"Bundesland-Filter: {bundesland}")
    lines.append("")

    for fach in sorted(tree, key=str.casefold):
        lines.append(fach)
        for land in sorted(tree[fach], key=str.casefold):
            lines.append(f"  {land}")
            for schulform in sorted(tree[fach][land], key=str.casefold):
                lines.append(f"    {schulform}")
                for klasse in sorted(tree[fach][land][schulform], key=_grade_sort_key):
                    lines.append(f"      - {klasse}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(message)s",
    )
    client = SparqlClient(args.endpoint)

    try:
        rows = client.select(alle_lehrplaene(args.bundesland, args.limit))
        lehrplaene = collect_labelled(rows, "lp", "lpLabel")
        logger.info("%d Lehrplan(e) geladen", len(lehrplaene))
        attributes_by_uri = fetch_attributes(client, [entry["uri"] for entry in lehrplaene]) if lehrplaene else {}
    except ValidationError as error:
        print(f"Ungueltige Eingabe: {error}", file=sys.stderr)
        return 2
    except SparqlError as error:
        print(f"SPARQL-Fehler: {error}", file=sys.stderr)
        return 1

    output = render(build_tree(lehrplaene, attributes_by_uri), len(lehrplaene), args.endpoint, args.bundesland)
    print(output, end="")
    if args.out:
        args.out.write_text(output, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
