"""Command line entry point."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from .export import write_csv, write_json
from .fetch import harvest
from .queries import ValidationError, schulfaecher
from .sparql import SparqlClient, SparqlError
from .vocab import DEFAULT_ENDPOINT, OPTIK_STICHWOERTER


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mem-optik",
        description="Laedt Physik-/Optik-Lehrplaene inkl. Themenbereiche, Kompetenzen und Bildungsstufen "
        "aus dem MEM-Triplestore.",
    )
    parser.add_argument("--fach", default="physik", help="Stichwort im Schulfach-Label (Default: physik)")
    parser.add_argument("--bundesland", help="Stichwort im Bundesland-Label, z. B. Sachsen")
    parser.add_argument(
        "--stichwort",
        action="append",
        dest="stichwoerter",
        metavar="WORT",
        help="Themen-Stichwort; mehrfach verwendbar. Ohne Angabe wird die Optik-Liste genutzt.",
    )
    parser.add_argument("--limit", type=int, help="Maximale Anzahl Lehrplaene (Smoke-Test)")
    parser.add_argument(
        "--endpoint",
        default=os.environ.get("MEM_SPARQL_ENDPOINT", DEFAULT_ENDPOINT),
        help="SPARQL-Endpoint (oder Umgebungsvariable MEM_SPARQL_ENDPOINT)",
    )
    parser.add_argument("--out", type=Path, default=Path("optik_lehrplaene.json"), help="Ziel-JSON")
    parser.add_argument("--csv", type=Path, help="Zusaetzliche flache CSV-Ausgabe")
    parser.add_argument(
        "--list-faecher",
        action="store_true",
        help="Nur die vorhandenen Schulfach-Bezeichnungen ausgeben und beenden",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Fortschritt protokollieren")
    parser.add_argument("--debug", action="store_true", help="Setze Log-Level auf DEBUG")
    return parser


def _print_faecher(client: SparqlClient, bundesland: str | None) -> None:
    for row in client.select(schulfaecher(bundesland)):
        print(f"{row.get('fachLabel', ''):<45} {row['fach']}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.debug else (logging.INFO if args.verbose else logging.WARNING),
        format="%(levelname)s %(message)s",
    )
    client = SparqlClient(args.endpoint)

    try:
        if args.list_faecher:
            _print_faecher(client, args.bundesland)
            return 0

        result = harvest(
            client,
            fach=args.fach,
            stichwoerter=args.stichwoerter or list(OPTIK_STICHWOERTER),
            bundesland=args.bundesland,
            limit=args.limit,
        )
    except ValidationError as error:
        print(f"Ungueltige Eingabe: {error}", file=sys.stderr)
        return 2
    except SparqlError as error:
        print(f"SPARQL-Fehler: {error}", file=sys.stderr)
        return 1

    write_json(result, args.out)
    outputs = [str(args.out)]
    if args.csv:
        write_csv(result, args.csv)
        outputs.append(str(args.csv))

    counts = result["anzahl"]
    print(f"{counts['lehrplaene']} Lehrplaene, {counts['treffer']} Treffer -> {', '.join(outputs)}")
    if result["diagnostik"].get("klassen_ohne_rolle"):
        print(
            f"Hinweis: {len(result['diagnostik']['klassen_ohne_rolle'])} Knotenklasse(n) ohne "
            "erkennbare Rolle - siehe diagnostik.klassen_ohne_rolle",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
