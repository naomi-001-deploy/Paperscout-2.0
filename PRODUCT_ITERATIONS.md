# paperscout Next-Level Iterationen

## Iteration 1 (jetzt umgesetzt): Research Signal Console
- Ziel: Von CLI zu einer klar geführten App mit schneller Time-to-Value.
- Ergebnis:
  - Funktionsfähiger UI-Entry-Point im Paket (`src/paperscout/ui.py`)
  - Command Center für Journals, Zeitraum, Fokusfrage und Scan-Run
  - Signal Feed mit Relevanz- und Recency-Score
  - Filter, Trendlinie, Top-Terms, CSV/XLSX-Export
- KPI:
  - Time-to-first-result < 2 Minuten
  - > 70% Runs mit mindestens einem verwertbaren Abstract

## Iteration 2 (jetzt umgesetzt): Researcher Workspaces
- Persistente Workspaces mit gespeicherter Scan-Konfiguration.
- Vergleichsansicht "neu seit letztem Run" auf Basis DOI/Metadaten-Key.
- Alert für neue High-Signal-Treffer.
- KPI:
  - Weekly Active Researchers
  - Wiederkehrrate nach 7 Tagen
  - Anteil Runs mit >0 neuen Treffern

## Iteration 3: Team-Kollaboration
- Shared Collections, Kommentare pro Paper, Rollen (PI, Postdoc, RA).
- DOI-Auswahl und Briefings als Team-Artefakte.
- KPI: Papers pro Team-Workspace, kollaborative Sessions/Woche.

## Iteration 4: AI Research Assistant
- Semantische Suche über lokale Ergebnisbasis.
- Auto-Briefing mit Evidenzzitaten und Unsicherheits-Flags.
- KPI: Anteil Runs mit Briefing, Nützlichkeitsrating der Zusammenfassungen.

## Iteration 5: Integrationen
- Zotero, Mendeley, Notion, Slack/Teams, E-Mail Digest.
- API/Webhooks für Labs und Institute.
- KPI: Export-/Integrationsquote, aktive Integrationen pro Workspace.

## Iteration 6: Trust & Scale
- Audit Trail, Reproduzierbarkeit, Quellen-Transparenz.
- Qualitätsscores für Abstract-Quelle und Metadaten.
- KPI: Fehlerrate pro 1.000 Abrufe, Datenvollständigkeit, NPS.
