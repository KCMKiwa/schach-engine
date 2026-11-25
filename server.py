#!/usr/bin/env python3
"""Schach-Engine mit Brett: Webserver, der die Analyse aus analyze.py (Stockfish) nutzt.

Start:  python3 server.py [--port 8000]
Dann im Browser http://localhost:8000 öffnen.
"""
import argparse
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import chess
import chess.engine

import analyze  # Analyse-Logik aus dem Schach-Engine-Skill (bester Zug, Brilliant/Great, Klassifizierung)

ROOT = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(ROOT, "static")

_engine = None
_engine_path = None
_lock = threading.Lock()


def engine():
    global _engine
    if _engine is None:
        _engine = chess.engine.SimpleEngine.popen_uci(analyze.find_engine(_engine_path))
        try:
            _engine.configure({"Threads": max(1, (os.cpu_count() or 2) - 1), "Hash": 256})
        except chess.engine.EngineError:
            pass
    return _engine


def status(board):
    out = {"fen": board.fen(), "turn": "w" if board.turn else "b", "check": board.is_check(),
           "legal": [m.uci() for m in board.legal_moves], "game_over": board.is_game_over()}
    if out["game_over"]:
        oc = board.outcome()
        names = {"CHECKMATE": "Schachmatt", "STALEMATE": "Patt", "INSUFFICIENT_MATERIAL": "Ungenügendes Material",
                 "THREEFOLD_REPETITION": "Dreifache Wiederholung", "FIVEFOLD_REPETITION": "Fünffache Wiederholung",
                 "SEVENTYFIVE_MOVES": "75-Züge-Regel", "FIFTY_MOVES": "50-Züge-Regel"}
        out["result"] = oc.result()
        out["reason"] = names.get(oc.termination.name, oc.termination.name)
    return out


def api_state(data):
    return status(chess.Board(data.get("fen") or chess.STARTING_FEN))


def api_best(data):
    """Bester Zug + Top-Linien + Brilliant-Kandidaten (Skill-Modus 'best')."""
    board = chess.Board(data["fen"])
    args = SimpleNamespace(time=float(data.get("time", 2.0)), depth=None,
                           multipv=int(data.get("multipv", 3)), max_sac_scan=12)
    with _lock:
        res = analyze.mode_best(engine(), board, args)
    return res


def api_play(data):
    """Zug ausführen und mit der Skill-Klassifizierung bewerten (Brilliant, Great, Best, ... Blunder)."""
    board = chess.Board(data["fen"])
    move = chess.Move.from_uci(data["move"])
    if move not in board.legal_moves:
        raise ValueError("Illegaler Zug")
    review = None
    if data.get("review", True) and board.legal_moves.count() > 1:
        limit = chess.engine.Limit(time=float(data.get("time", 1.0)))
        with _lock:
            review = analyze.evaluate_move(engine(), board, move, limit)
    san = board.san(move)
    board.push(move)
    return {"san": san, "uci": move.uci(), "review": review, **status(board)}


def api_ai(data):
    """KI-Zug: bei voller Stärke der beste Zug laut Skill-Analyse, sonst Stockfish mit reduziertem Skill-Level."""
    board = chess.Board(data["fen"])
    level = int(data.get("level", 20))
    t = float(data.get("time", 1.5))
    with _lock:
        eng = engine()
        if level >= 20:
            args = SimpleNamespace(time=t, depth=None, multipv=3, max_sac_scan=12)
            res = analyze.mode_best(eng, board, args)
            move = chess.Move.from_uci(res["lines"][0]["move_uci"])
            info = res["lines"][0]
        else:
            eng.configure({"Skill Level": level})
            try:
                r = eng.play(board, chess.engine.Limit(time=min(t, 0.3 + level * 0.05)))
            finally:
                eng.configure({"Skill Level": 20})
            move = r.move
            info = None
    san = board.san(move)
    board.push(move)
    return {"san": san, "uci": move.uci(), "info": info, **status(board)}


ROUTES = {"/api/state": api_state, "/api/best": api_best, "/api/play": api_play, "/api/ai": api_ai}
TYPES = {".html": "text/html; charset=utf-8", ".js": "application/javascript", ".css": "text/css"}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = "/index.html" if self.path in ("/", "") else self.path.split("?")[0]
        f = os.path.normpath(os.path.join(STATIC, path.lstrip("/")))
        if not f.startswith(STATIC) or not os.path.isfile(f):
            return self.send(404, {"error": "nicht gefunden"})
        with open(f, "rb") as fh:
            self.send(200, fh.read(), TYPES.get(os.path.splitext(f)[1], "application/octet-stream"))

    def do_POST(self):
        fn = ROUTES.get(self.path)
        if not fn:
            return self.send(404, {"error": "unbekannt"})
        try:
            data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            self.send(200, fn(data))
        except Exception as e:  # noqa: BLE001
            self.send(400, {"error": str(e)})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--engine", help="Pfad zur Stockfish-Datei (sonst STOCKFISH_PATH oder PATH)")
    a = ap.parse_args()
    global _engine_path
    _engine_path = a.engine
    engine()
    print(f"Schach-Engine läuft auf http://{a.host}:{a.port}  (Strg+C zum Beenden)")
    try:
        ThreadingHTTPServer((a.host, a.port), Handler).serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if _engine:
            _engine.quit()


if __name__ == "__main__":
    main()
