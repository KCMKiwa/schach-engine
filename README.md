# Schach-Engine mit Brett

Spielbares Schachbrett im Browser. Die KI rechnet mit **Stockfish** und der Analyse-Logik aus dem
Schach-Engine-Skill (`analyze.py`): bester Zug, Top-3-Varianten, Bewertung, Gewinnchance,
Brilliant-Erkennung (!!) sowie Zugbewertung wie im Chess.com-Review (Brillant, Großartig, Bester Zug … Patzer).

## Start

```bash
bash setup.sh          # installiert Stockfish + python-chess, falls nötig
python3 server.py      # danach http://localhost:8000 öffnen
```

## Funktionen
- Modi: gegen die KI als Weiß oder Schwarz, Analyse (beide Seiten selbst), KI gegen KI
- KI-Stärke 0–20 (20 = immer der beste Zug laut Engine-Analyse)
- „Besten Zug berechnen“: Pfeil auf dem Brett, Bewertung, Hauptvarianten, Brilliant-Kandidaten
- Jeder Zug wird klassifiziert, mit „Besser war …“ bei Fehlern
- Eval-Balken, Zugliste in deutscher Notation, Zug zurück, Brett drehen, FEN laden

## Dateien
- `server.py` – Webserver + API (`/api/best`, `/api/play`, `/api/ai`, `/api/state`)
- `analyze.py` – Analyse-Logik aus dem Skill (auch einzeln per Kommandozeile nutzbar)
- `static/index.html` – Brett und Oberfläche
