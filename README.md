# Schach-Engine mit Brett

Spielbares Schachbrett im Browser. Die KI rechnet mit **Stockfish** und der Analyse-Logik aus dem
Schach-Engine-Skill (`analyze.py`): bester Zug, Top-3-Varianten, Bewertung, Gewinnchance,
Brilliant-Erkennung (!!) sowie Zugbewertung wie im Chess.com-Review (Brillant, Großartig, Bester Zug … Patzer).

## Start

```bash
sudo apt-get install -y stockfish   # python-chess liegt schon im Ordner chess/
python3 server.py      # danach http://localhost:8000 öffnen
```

## Funktionen
- Am Anfang wählst du deine Seite (Weiß oder Schwarz), das Brett dreht sich passend.
- Du bewegst **beide Seiten selbst** (Figur ziehen oder anklicken), z. B. um eine laufende Partie nachzuspielen.
- Die Engine rechnet **nur, wenn deine Seite am Zug ist**: Pfeil auf dem Brett, Bewertung, Top-3-Varianten, Brilliant-Kandidaten.
- „Besten Zug ausführen“ spielt ihn für dich, oder automatisch per Häkchen.
- Deine Züge werden klassifiziert (Brillant … Patzer), mit „Besser war …“ bei Fehlern.
- Eval-Balken, Zugliste in deutscher Notation, Zug zurück, Brett drehen, FEN laden.

## Dateien
- `server.py` – Webserver + API (`/api/best`, `/api/play`, `/api/ai`, `/api/state`)
- `analyze.py` – Analyse-Logik aus dem Skill (auch einzeln per Kommandozeile nutzbar)
- `static/index.html` – Brett und Oberfläche
