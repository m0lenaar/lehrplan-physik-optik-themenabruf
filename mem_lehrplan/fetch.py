"""Orchestration: query the endpoint and assemble linked records.

Sequence, one query per step (plus chunking for VALUES blocks):

    Lehrpläne -> descriptive attributes -> matching nodes -> node classes
              -> node attributes -> direct parents -> assembled records

Levels are attached twice: once per Lehrplan and once per node. Where a node
carries no level of its own it inherits the Lehrplan's, and ``stufen_quelle``
records which of the two applied -- so a downstream consumer never has to guess
whether "Jahrgangsstufe 7" was asserted on the competency or on the curriculum.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from . import queries
from .classify import build_class_index, node_roles
from .sparql import SparqlClient, chunked, collect_labelled
from .vocab import (
    BUCKET_GENERIC,
    DESCRIPTIVE_PROPERTIES,
    ONTOLOGY,
    PROP_BESCHRIEBEN_VON,
    STUFEN_PROPERTIES,
    TYPE_ROOTS,
)

logger = logging.getLogger(__name__)

CHUNK_SIZE = 40

_PROPERTY_NAMES = {ONTOLOGY + pid: name for name, pid in DESCRIPTIVE_PROPERTIES.items()}
_GENERIC_PROPERTY = ONTOLOGY + PROP_BESCHRIEBEN_VON
_ROOT_BUCKETS = {ONTOLOGY + pid: name for name, pid in TYPE_ROOTS.items()}

# Buckets that count as an educational level, regardless of which of the two
# encodings (specific sub-property or generic property plus object type) the
# state graph used.
_STUFEN_BUCKETS = tuple(STUFEN_PROPERTIES)


def _select_chunked(client: SparqlClient, build, uris: list[str]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for chunk in chunked(uris, CHUNK_SIZE):
        rows.extend(client.select(build(list(chunk))))
    return rows


def _resolve_type_buckets(client: SparqlClient, type_uris: list[str]) -> dict[str, str]:
    """Map each class URI to a bucket name, following sub-class chains if needed."""
    buckets = {uri: _ROOT_BUCKETS[uri] for uri in type_uris if uri in _ROOT_BUCKETS}
    unresolved = [uri for uri in type_uris if uri not in buckets]
    if unresolved:
        for row in _select_chunked(client, queries.type_roots, unresolved):
            root = _ROOT_BUCKETS.get(row.get("root", ""))
            if root:
                buckets.setdefault(row["type"], root)
    return buckets


def fetch_attributes(client: SparqlClient, uris: list[str]) -> dict[str, dict[str, list[dict[str, str]]]]:
    """Map each subject URI to its descriptive attributes, grouped by name.

    Works for Lehrpläne and for tree nodes alike -- both carry the same
    descriptive properties. Statements using the generic super-property are
    bucketed by the object's ``rdf:type``; anything unrecognised lands in
    ``beschrieben_von`` so it stays visible instead of being dropped.
    """
    rows = _select_chunked(client, queries.descriptive_attributes, uris)

    # One statement can yield several rows (multiple object types), so collect
    # the types per statement before deciding on a single bucket.
    statements: dict[tuple[str, str, str], dict] = {}
    for row in rows:
        if not row.get("s") or not row.get("o"):
            continue
        key = (row["s"], row.get("p", ""), row["o"])
        entry = statements.setdefault(key, {"label": "", "types": set()})
        if not entry["label"] and row.get("oLabel"):
            entry["label"] = row["oLabel"]
        if row.get("oType"):
            entry["types"].add(row["oType"])

    all_types = sorted({t for entry in statements.values() for t in entry["types"]})
    type_buckets = _resolve_type_buckets(client, all_types) if all_types else {}

    grouped: dict[str, dict[str, list[dict[str, str]]]] = {}
    for (subject, predicate, obj), entry in statements.items():
        name = _bucket_for(predicate, entry["types"], type_buckets)
        if not name:
            continue
        bucket = grouped.setdefault(subject, {}).setdefault(name, [])
        candidate = {"uri": obj, "label": entry["label"]}
        if candidate not in bucket:
            bucket.append(candidate)
    return grouped


def _bucket_for(predicate: str, object_types: set[str], type_buckets: dict[str, str]) -> str | None:
    if predicate in _PROPERTY_NAMES:
        return _PROPERTY_NAMES[predicate]
    if predicate != _GENERIC_PROPERTY:
        return None
    for object_type in sorted(object_types):
        if object_type in type_buckets:
            return type_buckets[object_type]
    return BUCKET_GENERIC


def _stufen(attributes: dict[str, list[dict[str, str]]]) -> dict[str, list[dict[str, str]]]:
    return {name: attributes[name] for name in _STUFEN_BUCKETS if attributes.get(name)}


def fetch_nodes(client: SparqlClient, lehrplan_uri: str, keywords: list[str]) -> dict[str, dict]:
    """Matching descendants of one Lehrplan, with their class URIs collected."""
    nodes: dict[str, dict] = {}
    for row in client.select(queries.matching_nodes(lehrplan_uri, keywords)):
        node = nodes.setdefault(row["node"], {"uri": row["node"], "label": row.get("nodeLabel", ""), "typen": []})
        if row.get("type") and row["type"] not in node["typen"]:
            node["typen"].append(row["type"])
    return nodes


def fetch_parents(client: SparqlClient, node_uris: list[str]) -> dict[str, list[dict[str, str]]]:
    rows = _select_chunked(client, queries.direct_parents, node_uris)
    parents: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        bucket = parents.setdefault(row["node"], [])
        entry = {"uri": row["parent"], "label": row.get("parentLabel", "")}
        if entry not in bucket:
            bucket.append(entry)
    return parents


def _assemble_node(node: dict, index, attributes, parents, lehrplan_stufen) -> dict:
    own_stufen = _stufen(attributes.get(node["uri"], {}))
    return {
        "uri": node["uri"],
        "label": node["label"],
        "rollen": node_roles(node["typen"], index),
        "klassen": [{"uri": t, "label": index[t].label if t in index else ""} for t in node["typen"]],
        "stufen": own_stufen or lehrplan_stufen,
        "stufen_quelle": "knoten" if own_stufen else ("lehrplan" if lehrplan_stufen else "keine"),
        "eltern": parents.get(node["uri"], []),
    }


def _as_list(value: str | list[str] | None) -> list[str]:
    """Normalise a single string or a list of strings to a list."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return list(value)


def harvest(
    client: SparqlClient,
    fach: str | list[str],
    stichwoerter: list[str],
    bundesland: str | list[str] | None = None,
    limit: int | None = None,
) -> dict:
    """Collect all matching curricula with their topic areas and competencies.

    ``fach`` and ``bundesland`` accept a single keyword or a list of keywords;
    a curriculum is selected when its Schulfach label matches any ``fach``
    keyword. The Lehrplan match uses the direct ``LP_0000537`` Schulfach
    predicate (see :func:`mem_lehrplan.queries.lehrplaene_by_fach`), which also
    reaches Lehrpläne below the bounded class walk -- e.g. Bayern.
    """
    fach_list = _as_list(fach)
    if not fach_list:
        raise queries.ValidationError("at least one fach keyword is required")
    bundesland_list = _as_list(bundesland)
    lehrplan_rows = client.select(queries.lehrplaene_by_fach(fach_list, bundesland_list, limit))
    lehrplaene = collect_labelled(lehrplan_rows, "lp", "lpLabel")
    logger.info("%d Lehrplan(e) fuer Fach-Stichwort(e) %r", len(lehrplaene), fach_list)
    if not lehrplaene:
        return _result(fach_list, stichwoerter, bundesland_list, client.endpoint, [], {})

    lehrplan_uris = [entry["uri"] for entry in lehrplaene]
    lehrplan_attributes = fetch_attributes(client, lehrplan_uris)

    nodes_by_lehrplan = {}
    for uri in lehrplan_uris:
        nodes_by_lehrplan[uri] = fetch_nodes(client, uri, stichwoerter)
        logger.info("  %d Treffer in %s", len(nodes_by_lehrplan[uri]), uri)

    all_nodes = {uri: node for nodes in nodes_by_lehrplan.values() for uri, node in nodes.items()}
    node_uris = list(all_nodes)
    type_uris = sorted({t for node in all_nodes.values() for t in node["typen"]})

    index = build_class_index(_select_chunked(client, queries.class_roles, type_uris)) if type_uris else {}
    node_attributes = fetch_attributes(client, node_uris) if node_uris else {}
    parents = fetch_parents(client, node_uris) if node_uris else {}

    records = []
    for entry in lehrplaene:
        attributes = lehrplan_attributes.get(entry["uri"], {})
        lehrplan_stufen = _stufen(attributes)
        records.append(
            {
                "uri": entry["uri"],
                "label": entry["label"],
                "bundesland": attributes.get("bundesland", []),
                "schulfach": attributes.get("schulfach", []),
                "schulart": attributes.get("schulart", []),
                "stufen": lehrplan_stufen,
                "weitere": attributes.get(BUCKET_GENERIC, []),
                "treffer": [
                    _assemble_node(node, index, node_attributes, parents, lehrplan_stufen)
                    for node in nodes_by_lehrplan[entry["uri"]].values()
                ],
            }
        )

    diagnostics = {
        # "lehrplan_praedikate": collect_labelled(
        #     _select_chunked(client, queries.predicate_audit, lehrplan_uris), "p", "pLabel"
        # ),
        "klassen_ohne_rolle": sorted(
            {info.uri for info in index.values() if not info.rollen}
        ),
    }
    return _result(fach_list, stichwoerter, bundesland_list, client.endpoint, records, diagnostics)


def _result(fach, stichwoerter, bundesland, endpoint, records, diagnostics) -> dict:
    return {
        "abgerufen_am": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "endpoint": endpoint,
        "filter": {"fach": fach, "bundesland": bundesland, "stichwoerter": stichwoerter},
        "anzahl": {
            "lehrplaene": len(records),
            "treffer": sum(len(record["treffer"]) for record in records),
        },
        "lehrplaene": records,
        "diagnostik": diagnostics,
    }
