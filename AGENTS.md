# AGENTS.md

Arbeitshinweise für das `mem-optik`-Repository (Lehrplan-Abruf aus dem MEM-
Triplestore). Diese Datei ergänzt `README.md` und `DOKUMENTATION.md`; sie hält
die praxisrelevanten Fallstricke fest, die beim Arbeiten mit dem Live-Endpoint
aufgefallen sind.

## Projektdaten

- SPARQL-Endpoint: `https://sparql.mem.edufeed.org/sparql/` (Virtuoso, kein
  Reasoning, keine CORS; Default im Code über `mem_lehrplan/vocab.py`).
- Kein Reasoning: Sub-Properties und Sub-Klassen müssen explizit benannt werden.
- Membership der Bayern-Lehrpläne ist **nicht** über die abstrakte Klasse
  `LP_0000438` erreichbar (siehe unten).
- Tests: `python3 -m unittest discover` (offline, ohne Netz).
- Standardbibliothek only; Python ≥ 3.10.

## Zwei Kodierungen für Kontext und Stufen (WICHTIG)

Alle Bundesländer asserten ihre beschreibenden Angaben teils über die
*spezifischen* Sub-Properties, teils über die generische Ober-Property
`LP_0000024` ("wird beschrieben von"):

- **Spezifisch**: `LP_0000537` (hat Schulfach), `LP_0000029` (von Bundesland),
  `LP_0000812` (für Schulart), `LP_0000026`/`LP_0000047`/… (Stufen).
- **Generisch**: dieselben Angaben als `LP_0000024 → Objekt`, die Einordnung
  hängt dann am `rdf:type` des Objekts.

`mem_lehrplan/fetch.py:fetch_attributes` erkennt beides (Bucket per
Object-Type) — beim Filtern in Python immer `fetch_attributes` benutzen, nicht
die spezifischen Properties annehmen.

## Bayern-Lehrpläne werden von den Standard-Queries NICHT gefunden

`queries.lehrplaene()` und `queries.alle_lehrplaene()` gehen über einen
* beschränkten* Klasswalk von `LP_0000438` (Tiefe `MAX_LEHRPLAN_SUBCLASS_DEPTH`
= 2). Die bayerischen Klassen `Fachlehrplan (BY)` (`LP_0002043`) und
`Lehrplanfragment (BY)` (`LP_0002044`) liegen **tiefer** als diese Grenze und
werden deshalb von der Walk übersprungen — `queries.lehrplaene("sachunterricht", "Bayern")`
liefert 0 Treffer, obwohl ~13 Heimat- und Sachunterricht-Lehrpläne existieren.

Behoben in `heimat_sachunterricht_by.py` durch **direktes** Matchen auf
`LP_0000537` + Schulfach-Label (ohne den Klassenwalk) und anschließendes
Filtern von Bundesland/Schulart per `fetch_attributes`. Dieselbe Einschränkung
gilt für jedes Skript, das Bayern-Lehrpläne finden will.

## Zwei URI-Formen pro Bayern-Lehrplan

Jeder Bayern-Lehrplan existiert unter zwei URIs:

- `https://lp-bavaria.org/lis_live_isb.c.<id>.de` — **Lehrplanfragment**; hier
  hängt der ganze Baum (Lernbereiche/Kompetenzen) plus vollständige Attribute
  (Schulfach, Bundesland, Schulart, Jahrgangsstufen).
- `https://lp-bavaria.org/lehrplanplus-lis_live_isb.c.<id>.de` — nur Bundesland
  und Titel (via `beschrieben_von`); **kein Baum**.

Für den Topologie-Abruf immer die `lis_live_isb.c.<id>.de`-URI verwenden.

## Bayern-Grundschule-Struktur (Heimat- und Sachunterricht)

`Lernbereich (BY)` (`LP_0002046`, themenbereich) → Unter-`Lernbereich (BY)` →
`Kompetenzerwartung (BY)` (`LP_0002049`, kompetenz) + `Inhalt zu den
Kompetenzen (BY)` (`LP_0002050`, inhalt). Zwei Lehrpläne: 1/2 und 3/4.
RP dagegen: ein Lehrplan (1-4) mit `Kompetenzbereich (RP)` / `Kompetenz (RP)`.

## Bekannter, vorbestehender Testfehler

`test_diagnostics_report_used_predicates` (`tests/test_fetch.py`) schlägt fehl:
In der Arbeitskopie ist in `mem_lehrplan/fetch.py` der Block
`diagnostics["lehrplan_praedikate"]` auskommentiert (Pre-existing-Änderung,
nicht von hier). Falls die Suite grün sein soll, muss dieser Block entweder
wieder aktiviert oder der Test angepasst werden.

## Vorgehen für ein neues Bundesland-Fach (Muster)

1. Lehrpläne per `LP_0000537`-Schulfach-Match + `fetch_attributes` auswählen
   (statt `queries.lehrplaene`, damit Bayern mitläuft).
2. Baum per `build_tree` aus `sachunterricht_rp.py` holen (generisch, liefert
   `uri`, `label`, `rollen`, `eltern_uri`).
3. Rolle je Klasse über `class_roles`/`node_roles` (CE-Bereich/
   Kompetenzspezifikation/CE-Lerninhalt + `LP_0000483`-Funktionswalk).
4. Standalone-Skript im Repo-Root, Markdown-Output, Tests in `tests/`.

Siehe `sachunterricht_rp.py` (RP) und `heimat_sachunterricht_by.py` (Bayern)
als Referenz-Implementierungen.
