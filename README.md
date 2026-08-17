# mem-optik

Ausführliche Projektdokumentation mit Methodik, Ergebnissen und Übertragung auf
andere Themen: [DOKUMENTATION.md](DOKUMENTATION.md).

Lädt aus dem MEM-Triplestore (Projekt MEM / FWU) alle Lehrpläne eines Fachs,
filtert deren Themenbereiche und Kompetenzen auf ein Thema (Default: Optik) und
verknüpft jeden Treffer mit den Bildungsstufen des Lehrplans bzw. des Knotens.

Keine Abhängigkeiten außer der Python-Standardbibliothek (Python ≥ 3.10).

## Nutzung

```bash
# Vollabruf: alle Physik-Lehrpläne, Optik-Stichwörter, JSON + CSV
python -m mem_lehrplan.cli --csv optik.csv -v

# Ein Bundesland, kleiner Smoke-Test
python -m mem_lehrplan.cli --bundesland Sachsen --limit 3 -v

# Eigene Stichwortliste
python -m mem_lehrplan.cli --stichwort Optik --stichwort "Licht und Sehen"

# Welche Fachbezeichnungen gibt es überhaupt? (siehe Einschränkungen)
python -m mem_lehrplan.cli --list-faecher --bundesland Bayern
```

Endpoint per `--endpoint` oder `MEM_SPARQL_ENDPOINT`; Default ist
`https://sparql.mem.edufeed.org/sparql/`.

### Faecheruebersicht

Eine hierarchische Liste aller im Store vorhandenen Faecher mit Bundesland,
Schulform und Klassenstufen erzeugt das separate Skript:

```bash
python3 faecher_uebersicht.py
python3 faecher_uebersicht.py --bundesland Sachsen --limit 50 -o faecher.txt
```

Die Ausgabe ist nach `Fach -> Bundesland -> Schulform -> Klassenstufe`
geordnet. Fehlende Klassenstufen werden, soweit moeglich, aus dem
Lehrplantitel abgeleitet.

## Gegliederte Uebersicht

```bash
python optik_uebersicht.py optik_lehrplaene.json
python optik_uebersicht.py optik_lehrplaene.json -o uebersicht.md --alle
```

Erzeugt ein Markdown-Dokument, gegliedert nach Bildungsstufe -> Bundesland ->
Klassenstufe -> Lehrplan -> Bereich, mit Kompetenzen und Inhalten als Listen.
Eigenstaendiges Skript, nur Standardbibliothek, liest ausschliesslich die JSON.

Fehlende Stufenangaben werden ueber eine Leiter erschlossen (asserted Schulstufe
-> asserted Jahrgangsstufe -> Lehrplantitel) und im Dokument als abgeleitet
gekennzeichnet; der Abschnitt *Datenlage* zaehlt aus, wie viele Eintraege aus
Daten und wie viele aus Ableitung stammen. Treffer, in denen das Stichwort in
einem laengeren Wort begraben ist ("Licht" in "Wahlpflichtlernbereich"), werden
per Default weggelassen; `--alle` nimmt sie mit auf.

## Auswertung

```bash
python -m mem_lehrplan.report optik_lehrplaene.json
python -m mem_lehrplan.report optik_lehrplaene.json --md bericht.md --top 20
```

Liest nur die Ergebnisdatei, kein Endpoint-Zugriff. Der Bericht zeigt Treffer je
Bundesland, Rollenverteilung, **Stufen-Abdeckung** (wie viele Treffer ueberhaupt
eine Bildungsstufe haben und woher sie stammt), **Stichwort-Praezision** mit
Beispiel-Labels je Stichwort, verdaechtige Treffer (Stichwort kommt nur
wortintern vor, z. B. "Licht" in "Pflichtbereich"), Knotenklassen ohne erkennbare
Rolle sowie Ranglisten. Ausgabe ist reines ASCII, damit sie in `cmd.exe`
lesbar bleibt.

## Ausgabe

`optik_lehrplaene.json`:

```json
{
  "anzahl": { "lehrplaene": 1, "treffer": 2 },
  "lehrplaene": [{
    "uri": "https://lp-sachsen.org/resource/522",
    "label": "Physik Oberschule (SN)",
    "bundesland": [{ "uri": "…", "label": "Sachsen" }],
    "schulart": [], "schulfach": [{ "label": "Physik" }],
    "stufen": { "schulstufe": [{ "label": "Sekundarbereich I" }] },
    "treffer": [{
      "uri": "https://lp-sachsen.org/resource/7053",
      "label": "Lichtbrechung an Linsen und Prismen",
      "rollen": ["kompetenz", "inhalt"],
      "klassen": [{ "label": "Lernziel und Lerninhalt (SN)" }],
      "stufen": { "jahrgangsstufe": [{ "label": "Klassenstufe 7" }] },
      "stufen_quelle": "knoten",
      "eltern": [{ "label": "Lernbereich 2: Optik" }]
    }]
  }],
  "diagnostik": { "lehrplan_praedikate": [], "klassen_ohne_rolle": [] }
}
```

`--csv` schreibt eine Zeile pro Treffer (Semikolon-getrennt) mit den
Stufen-Spalten direkt neben Rolle, Elternknoten und Label — für Pivot-Auswertung
über Länder und Jahrgangsstufen.

* `rollen` — `themenbereich`, `kompetenz`, `inhalt`, `unbekannt`; mehrfach möglich.
* `stufen_quelle` — `knoten`, wenn die Stufe am Treffer selbst hängt, `lehrplan`,
  wenn sie vom Lehrplan geerbt wurde, `keine`, wenn keine vorhanden ist.
* `eltern` — direkter Oberknoten. Bei Top-Level-Knoten ist das der Lehrplan selbst.
* `diagnostik.lehrplan_praedikate` — alle tatsächlich verwendeten Prädikate;
  darüber wird sichtbar, wenn ein Bundesland eine Stufen-Property nutzt, die
  `vocab.STUFEN_PROPERTIES` noch nicht kennt.

## Datenmodell

Alle IRIs sind gegen `lp-base.ttl`/`lp-full.ttl` der
[Lehrplan-Ontologie](https://github.com/FWU-DE/lehrplan-ontologie) geprüft.

| IRI | Bedeutung | Rolle im Skript |
|---|---|---|
| `LP_0000438` | Lehrplan (abstrakt) | Einstieg über `rdfs:subClassOf*` |
| `LP_0000029` / `LP_0000537` / `LP_0000812` | Bundesland / Schulfach / Schulart | Kontext |
| `LP_0000024` | wird beschrieben von (Ober-Property) | Bildungsstufe, Zuordnung per Objekt-Typ |
| `LP_0000026` | hat Jahrgangsstufe | Bildungsstufe |
| `LP_0000047` | hat Schulstufe (Primar / Sek I / Sek II) | Bildungsstufe |
| `LP_0000578` | hat Niveaustufe (BE/BB) | Bildungsstufe |
| `LP_0000833` | hat Bildungsgangniveau | Bildungsstufe |
| `LP_0000840` | hat Niveau | Bildungsstufe |
| `obo:BFO_0000051` | hat Teil | Baumkante |
| `LP_0000483` | has function specification | Rollenbestimmung |
| `LP_0000479` / `LP_0000480` / `LP_0000497` | Kompetenz- / Lerninhalts- / Bereichsfunktion | Rollenwerte |
| `LP_0000349` / `LP_0000263` / `LP_0000332` | CE-Bereich / CE-Kompetenzspezifikation / CE-Lerninhalt | Rollenbestimmung (Fallback) |
| `LP_0000009` / `LP_0000020` / `LP_0000443` / `LP_0000028` / `LP_0000037` | Jahrgangsstufe / Schulstufe / Niveaustufe / Bildungsgangniveau / Niveau | Zieltypen hinter `LP_0000024` |

**Zwei Kodierungen fuer Bildungsstufen.** Die Laendergraphen nutzen nicht nur die
spezifischen Sub-Properties, sondern asserten teils direkt die Ober-Property
`LP_0000024` (belegt durch den Praedikat-Audit am Berliner Lehrplan, der
`LP_0000024` traegt, aber weder `LP_0000026` noch `LP_0000047`). In diesem Fall
entscheidet der `rdf:type` des Objekts, welche Stufenart vorliegt; da etwa
`Niveau` bis Tiefe 4 verschachtelt ist, loest `queries.type_roots` die
Unterklassen beschraenkt auf. Nicht zuordenbare Objekte landen im Feld
`weitere`, statt verworfen zu werden.

Vier Eigenschaften des Endpoints prägen jede Query:

1. **Kein Reasoning.** Sub-Klassen und Sub-Properties müssen explizit
   aufgezählt bzw. per Property-Path gelaufen werden. `lp:LP_0000024`
   ("wird beschrieben von") als Sammel-Property funktioniert nicht.
2. **`BFO_0000051` ist transitiv über-asserted.** Ein Hop vom Lehrplan liefert
   deshalb *alle* Nachfahren — für einen flachen Themen-Harvest ideal. Für den
   Elternknoten ist dagegen ein `FILTER NOT EXISTS` nötig, sonst gilt jeder
   Vorfahre als Elternteil.
3. **Labels der Länderdaten sind meist ohne Sprachtag.** `FILTER(lang(?l)="de")`
   würde sie verwerfen; das Skript akzeptiert `"de"` und `""`.
4. **Transitivpfade (`*`, `+`) sprengen den Speicher.** Ein unbeschränktes
   `?c rdfs:subClassOf* lp:LP_0000438`, gejoint gegen die Instanzdaten, endet in
   `Virtuoso 42000 Error TN…: Exceeded 1000000000 bytes in transitive temp
   memory` (HTTP 500). Alle Closures sind deshalb als beschränkte UNIONs
   ausgeschrieben — Fixed-Length-Pfade nutzen die Transitiv-Engine gar nicht.
   Die Tiefen sind gemessen, nicht geschätzt (`tools/measure_depths.py`):
   Lehrplan hat 16 direkte Unterklassen und maximale Tiefe 1, CE-Bereich Tiefe 3,
   die `owl:intersectionOf`-Listen höchstens 7 Glieder. Die Grenzen in
   `vocab.py` liegen jeweils eine Stufe darüber. Ein Regressionstest verbietet
   `*` und `+` in allen Templates.

Die didaktische Rolle steckt in der Ontologie in zwei verschiedenen Formen:
CE-Bereich-Klassen (`Lernbereich (SN)`, `Themenfeld (BB)`) hängen über eine
normale `rdfs:subClassOf`-Kette, Kompetenz- und Inhaltsklassen
(`Kompetenzerwartung (BY)`, `Kompetenz (RP)`) dagegen unter einer anonymen
`owl:intersectionOf`-Klasse mit `owl:hasValue` auf ein Funktions-Individuum.
`queries.class_roles` fragt beide Wege ab.

## Tests

Aus dem Projektstamm (dem Ordner mit `mem_lehrplan/`):

```bash
python -m unittest discover      # 73 Tests, offline, ohne Netz
```

Nicht `-s tests -t .` verwenden: unter Windows scheitert das mit
`AssertionError: Path must be within the project`. Explizite Alternative:

```bash
python -m unittest tests.test_queries tests.test_classify tests.test_fetch tests.test_report tests.test_uebersicht tests.test_sparql_syntax
```

Optional gegen die echten Ontologie-Axiome — verifiziert die Rollenlogik
(Themenbereich vs. Kompetenz) und die beschränkten Pfade:

```bash
pip install rdflib
curl -O https://raw.githubusercontent.com/FWU-DE/lehrplan-ontologie/main/lp-full.ttl
python tools/ontology_smoke_test.py lp-full.ttl     # endet mit ALL CHECKS PASSED
python tools/measure_depths.py lp-full.ttl          # Grenzen in vocab.py pruefen
```

## Einschränkungen

* **Live-Status.** Ein Lauf ueber alle Bundeslaender lieferte 14 Physik-Lehrplaene
  (SN, RP, BE) und 472 Treffer. Die Stufen-Erfassung ueber `LP_0000024` ist danach
  ergaenzt worden und nur gegen den lokalen Graphen verifiziert, nicht live.
* **Praezision des Stichwortfilters.** `REGEX` kennt keine Wortgrenze: "Licht"
  trifft auch "Pflichtbereich", "Sehen" auch "vorgesehen". Der Report weist das
  unter "Verdaechtige Treffer" aus; die Stichwortliste in `vocab.py` sollte nach
  dem ersten Bericht nachgeschaerft werden.
* **Laufzeit der Knotensuche unbekannt.** `matching_nodes` filtert per `REGEX`
  über die Labels aller Nachfahren eines Lehrplans. Falls das am Live-Endpoint
  in Timeouts läuft, ist Virtuosos Volltextindex die Alternative:
  `?nodeLabel bif:contains "'Optik' or 'Linse'"` statt des `REGEX`-Filters.
* **Datenbestand.** Laut `FWU-DE/mem-mcp` liegen Lehrplandaten nur für BY, SN,
  RP, BB und BE vor.
* **Integrierte Fächer.** `--fach physik` trifft nur explizit als Physik
  getaggte Lehrpläne. "Natur und Technik" (BY) oder vergleichbare
  Verbundfächer enthalten Optik-Inhalte, fallen aber durch das Raster —
  `--list-faecher` zeigt die real vorhandenen Bezeichnungen.
* **Stichwortfilter bleibt lexikalisch.** Ein Lernbereich "Wie wir die Welt
  wahrnehmen" ohne Optik-Vokabular wird nicht gefunden. Ob die Knoten
  SKOS-Referenzen in die `mem-skos-vocabs` tragen, die eine konzeptbasierte
  Selektion erlauben würden, ist ungeprüft.
* **Laufzeit.** Eine Query pro Lehrplan für die Knotensuche. Bei vielen
  Lehrplänen dauert der Abruf entsprechend; das Skript parallelisiert nicht.
