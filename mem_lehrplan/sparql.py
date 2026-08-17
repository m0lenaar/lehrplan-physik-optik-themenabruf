"""Minimal SPARQL SELECT client.

Uses urllib from the standard library: the only thing needed beyond a plain
HTTP POST is JSON parsing, so a third-party HTTP dependency would not pay for
itself here.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from typing import Iterable, Iterator, Sequence

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 180


class SparqlError(RuntimeError):
    """Raised when the endpoint refuses or fails a query."""


class SparqlClient:
    """Executes SELECT queries and returns flattened bindings.

    Each result row is a ``dict[str, str]`` mapping variable name to the
    binding's lexical value. Unbound OPTIONAL variables are simply absent from
    the row, which keeps the calling code free of ``None`` checks.
    """

    def __init__(self, endpoint: str, timeout: int = DEFAULT_TIMEOUT) -> None:
        self.endpoint = endpoint
        self.timeout = timeout

    def select(self, query: str) -> list[dict[str, str]]:
        payload = urllib.parse.urlencode({"query": query}).encode("utf-8")
        request = urllib.request.Request(
            self.endpoint,
            data=payload,
            headers={
                "Accept": "application/sparql-results+json",
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "User-Agent": "mem-optik/1.0 (+https://github.com/FWU-DE/mem-mcp)",
            },
        )
        logger.debug("POST %s (%d chars):\n%s", self.endpoint, len(query), query)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                document = json.load(response)
        except urllib.error.HTTPError as error:
            # Virtuoso returns the SPARQL parse error in the body; it is the
            # single most useful piece of information when a query is wrong.
            detail = error.read().decode("utf-8", "replace")[:600]
            raise SparqlError(f"HTTP {error.code} from {self.endpoint}: {detail}") from error
        except (urllib.error.URLError, TimeoutError) as error:
            raise SparqlError(f"cannot reach {self.endpoint}: {error}") from error
        except json.JSONDecodeError as error:
            raise SparqlError(f"endpoint did not return SPARQL JSON: {error}") from error

        try:
            bindings = document["results"]["bindings"]
        except (KeyError, TypeError) as error:
            raise SparqlError("unexpected SPARQL JSON shape") from error
        return [{name: cell["value"] for name, cell in row.items()} for row in bindings]


def chunked(items: Sequence[str], size: int) -> Iterator[Sequence[str]]:
    """Split a sequence so VALUES blocks stay within a sane query length."""
    if size < 1:
        raise ValueError("size must be >= 1")
    for start in range(0, len(items), size):
        yield items[start : start + size]


def collect_labelled(rows: Iterable[dict[str, str]], uri_var: str, label_var: str) -> list[dict[str, str]]:
    """Deduplicate ``{uri, label}`` pairs while preserving first-seen order."""
    seen: dict[str, dict[str, str]] = {}
    for row in rows:
        uri = row.get(uri_var)
        if not uri:
            continue
        entry = seen.setdefault(uri, {"uri": uri, "label": ""})
        if not entry["label"] and row.get(label_var):
            entry["label"] = row[label_var]
    return list(seen.values())
