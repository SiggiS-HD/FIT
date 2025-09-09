FIT – Auswertung von Garmin FIT-Dateien (GUI)

Kurzbeschreibung
- Python-Tool mit grafischer Oberfläche zur Auswertung von Garmin-FIT-Dateien.
- Der Einstiegspunkt ist `fit_analyze_gui_v4.py`.

Voraussetzungen
- Python 3.9 oder neuer
- Optional: Virtuelle Umgebung (empfohlen)

Schnellstart (Windows, PowerShell)
- `python -m venv venv`
- `venv\\Scripts\\Activate`
- `python fit_analyze_gui_v4.py`

Hinweise
- Lokale Datenordner `Touren/` und `dev/` sind bewusst nicht Teil des Repos und in `.gitignore` eingetragen.
- Lege keine Geheimnisse (Tokens, Passwörter) ins Repo. Die Datei `GITHUB_TOKEN.txt` ist ausgeschlossen.

Was macht der Code genau?
- Einstieg: `fit_analyze_gui_v4.py` kann per GUI (Tkinter) oder per CLI gestartet werden. Ohne Argumente öffnet sich ein Dateidialog zur Auswahl einer `.fit`-Datei und es werden drei Werte abgefragt: Nachladeenergie in kWh (Steckdose), Wall→Battery‑Effizienz in %, Muskeleffizienz in %.
- Parsing: Die FIT‑Datei wird mit `fitparse` eingelesen. Es werden `record`‑Nachrichten (Zeitreihen) sowie `session`/`lap` (Aggregatdaten) extrahiert. Relevante Felder: Zeitstempel, Position (Latitude/Longitude in Semikreisen → Grad), Höhe, Geschwindigkeit, Distanz, Herzfrequenz, Kadenz, Leistung, Temperatur.
- Aufbereitung:
  - Zeit wird nach UTC normalisiert und später für Darstellungen nach `Europe/Berlin` umgewandelt.
  - Distanz wird aus GPS neu aufgebaut, falls sie in der Datei fehlt (Haversine‑Formel).
  - Geschwindigkeit wird aus Δs/Δt rekonstruiert, wenn mehr als 50% der Werte fehlen.
  - Höhe wird, falls genügend Werte vorhanden sind, über Interpolation geglättet.
- Kennzahlen (Beispiele):
  - Gesamt‑ und Bewegungszeit, Strecke, Durchschnitts‑/Max‑Geschwindigkeit, Höhenmeter (positiver Höhengewinn).
  - Durchschnitt/Maximum für Herzfrequenz, Kadenz, Leistung, Temperatur (falls vorhanden).
  - Fahrerarbeit: Integration der Leistung über die Zeit → Arbeit in Joule/Wh.
  - Motorenergie: Aus der eingegebenen Nachladeenergie und Wall→Battery‑Effizienz berechnet.
  - Gesamtarbeit: Summe aus Fahrerarbeit und Motorenergie.
  - Kalorien: Mechanische Energie → Nahrungskalorien via Muskeleffizienz (inkl. Referenzbereich 20–25%).
- Exporte:
  - Zeitreihe als CSV mit Semikolon‑Trennzeichen und Komma als Dezimaltrennzeichen; Zeitstempel in Berlin‑Zeit (`timestamp_iso`).
  - Zusammenfassung als JSON mit allen berechneten Kennzahlen und Eingaben.
- Ausgabeorte: Dateien werden neben der Eingangsdaten erstellt, mit Suffix `_analysis` (z. B. `tour.fit` → `tour_analysis.csv`/`.json`).
- CLI‑Aufruf (optional):
  - `python fit_analyze_gui_v4.py <pfad.zur.fit>`
  - Optional: `--wall-energy-kwh 0.5 --wall2battery-eff-pct 82.5 --muscle-eff-pct 24.0`
- GUI‑Hinweis: Falls Tkinter nicht verfügbar ist, arbeitet das Skript nur über die CLI.
