#!/usr/bin/env python3
"""Schach-Analyse mit Stockfish: bester Zug, Brilliant-/Great-Move-Erkennung, Partie-Bewertung.

Modi:
  best   Stellung -> beste Züge (MultiPV) + Suche nach Brilliant-Opfern unter allen legalen Zügen
  move   Stellung + Zug -> Klassifizierung dieses einen Zugs
  game   PGN / Zugliste -> jeden Zug klassifizieren, Zusammenfassung + Genauigkeit

Stellung angeben mit --fen "<FEN>" oder --moves "e4 e5 Nf3" (ab Grundstellung) oder beidem
(Züge werden dann ab der FEN gespielt). Partien mit --pgn <datei> oder --moves.

Ausgabe: lesbarer Text (Deutsch) oder --json.
"""
import argparse
import io
import json
import math
import os
import shutil
import sys

try:
    import chess
    import chess.engine
    import chess.pgn
except ImportError:
    sys.exit("python-chess fehlt. Bitte zuerst scripts/setup.sh ausführen.")

VALUES = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 0}
MATE_CP = 10000
PIECE_DE = {chess.PAWN: "Bauer", chess.KNIGHT: "Springer", chess.BISHOP: "Läufer", chess.ROOK: "Turm",
            chess.QUEEN: "Dame", chess.KING: "König"}

# Schwellen in Gewinnwahrscheinlichkeits-Prozentpunkten (Verlust ggü. bestem Zug), angelehnt an
# die verbreitete Lichess/Chess.com-Logik. Siehe references/klassifizierung.md.
T_BEST, T_EXCELLENT, T_GOOD, T_INACC, T_MISTAKE = 1.0, 2.5, 5.0, 10.0, 20.0
BRILLIANT_MAX_LOSS = 2.5      # Opfer muss (fast) bester Zug sein
BRILLIANT_MIN_WP = 45.0       # nach dem Opfer darf man nicht verloren stehen
BRILLIANT_MAX_WP_BEFORE = 97.0  # wer schon total gewinnt, bekommt kein "!!" für ein Opfer
SAC_MIN = 1                   # mind. 1 Bauerneinheit netto geopfert ...
SAC_MIN_PIECE = 3             # ... und die hängende Figur ist mind. eine Leichtfigur (reine Bauernopfer zählen nicht)
GREAT_GAP = 15.0              # Abstand bester vs. zweitbester Zug (Win%) für "Great / einziger Zug"
GREAT_MAX_SECOND_WP = 85.0    # wenn auch der zweitbeste Zug klar gewinnt, ist der beste kein "einziger Zug"


def find_engine(explicit=None):
    for c in (explicit, os.environ.get("STOCKFISH_PATH"), shutil.which("stockfish"),
              "/usr/games/stockfish", "/usr/local/bin/stockfish", "/opt/homebrew/bin/stockfish"):
        if c and os.path.exists(c):
            return c
    sys.exit("Stockfish nicht gefunden. scripts/setup.sh ausführen oder --engine / STOCKFISH_PATH setzen.")


def cp_of(score, pov):
    """Score -> Centipawns aus Sicht von pov (Matt = +-MATE_CP, näheres Matt höher)."""
    s = score.pov(pov)
    if s.is_mate():
        m = s.mate()
        return MATE_CP - abs(m) if m > 0 else -MATE_CP + abs(m)
    return s.score()


def win_pct(cp):
    if cp >= MATE_CP - 1000:
        return 100.0
    if cp <= -MATE_CP + 1000:
        return 0.0
    return 50 + 50 * (2 / (1 + math.exp(-0.00368208 * cp)) - 1)


def fmt_score(score, pov):
    s = score.pov(pov)
    if s.is_mate():
        m = s.mate()
        return f"#{m}" if m > 0 else f"#-{abs(m)}"
    return f"{s.score() / 100:+.2f}"


# ---------- Opfer-Erkennung (Static Exchange Evaluation über legale Züge) ----------

def see(board, square, depth=0):
    """Materialgewinn (Bauerneinheiten) für die Seite am Zug, wenn sie auf `square` abtauscht.
    Nutzt legale Züge -> Fesselungen und Röntgenangriffe werden automatisch berücksichtigt."""
    target = board.piece_at(square)
    if target is None or depth > 12:
        return 0
    caps = [m for m in board.legal_moves if m.to_square == square]
    if not caps:
        return 0
    m = min(caps, key=lambda mv: VALUES[board.piece_at(mv.from_square).piece_type])
    gain = VALUES[target.piece_type] if target.piece_type != chess.KING else 100
    board.push(m)
    if board.is_checkmate():
        board.pop()
        return gain
    val = gain - see(board, square, depth + 1)
    board.pop()
    return max(0, val)


def threats_against(board, color):
    """Max. Material, das der Gegner von `color` sofort gewinnen kann (Board: Gegner am Zug)."""
    best, piece, ptype = 0, 0, None
    for sq in chess.SquareSet(board.occupied_co[color]):
        p = board.piece_at(sq)
        if p.piece_type == chess.KING:
            continue
        v = see(board, sq)
        if v > 0 and (v, VALUES[p.piece_type]) > (best, piece):
            best, piece, ptype = v, VALUES[p.piece_type], p.piece_type
    return best, piece, ptype


def sacrifice_amount(board, move):  # -> (netto, geopferte Figurenart)
    """Netto-Material (Bauerneinheiten), das `move` dem Gegner anbietet. 0 = kein (Figuren-)Opfer.
    Zählt nur, wenn dabei mind. eine Leichtfigur (Wert >= SAC_MIN_PIECE) hängen gelassen wird."""
    me = board.turn
    captured = 0
    if board.is_en_passant(move):
        captured = 1
    elif board.piece_at(move.to_square):
        captured = VALUES[board.piece_at(move.to_square).piece_type]
    # Drohungen gegen uns vor dem Zug (Nullzug), um "schon hängende" Figuren nicht doppelt zu zählen
    # Nullzug auch im Schach: der König selbst wird nie als Ziel gezählt, so bleiben
    # bereits hängende Figuren korrekt "vorbelastet" (sonst falsche Opfer bei Schachausweichen).
    b0 = board.copy(stack=False)
    b0.push(chess.Move.null())
    before = threats_against(b0, me)[0]
    b1 = board.copy(stack=False)
    b1.push(move)
    if b1.is_checkmate():
        return 0, None
    after, piece, ptype = threats_against(b1, me)
    if piece < SAC_MIN_PIECE:
        return 0, None
    promo_gain = (VALUES[move.promotion] - 1) if move.promotion else 0
    net = after - before - captured - promo_gain
    return (net, ptype) if net >= SAC_MIN else (0, None)


# ---------- Engine-Helfer ----------

def analyse(engine, board, limit, multipv=1, root_moves=None):
    kw = {"multipv": multipv}
    if root_moves:
        kw["root_moves"] = root_moves
    info = engine.analyse(board, limit, **kw)
    return info if isinstance(info, list) else [info]


def pv_san(board, pv, n=8):
    b = board.copy()
    out = []
    for mv in pv[:n]:
        if mv not in b.legal_moves:
            break
        num = f"{b.fullmove_number}." if b.turn == chess.WHITE else (f"{b.fullmove_number}..." if not out else "")
        out.append(f"{num}{b.san(mv)}")
        b.push(mv)
    return " ".join(out)


def already_winning(best_cp, second_cp):
    """True, wenn man schon so klar gewinnt, dass ein Opfer kein '!!' verdient.
    Ausnahme: nur der beste Zug erzwingt Matt (z.B. Damenopfer mit Matt) – das bleibt brillant."""
    if win_pct(best_cp) <= BRILLIANT_MAX_WP_BEFORE:
        return False
    forced_mate_only_here = best_cp >= MATE_CP - 1000 and (second_cp is None or second_cp < MATE_CP - 1000)
    return not forced_mate_only_here


def classify(loss, is_top, sac, wp_after, best_cp, second_cp, only_legal, mates_now=False):
    """Gibt (Label, Symbol) zurück. best_cp/second_cp: Bewertung der zwei besten Züge (Sicht Ziehender)."""
    if sac and loss <= BRILLIANT_MAX_LOSS and wp_after >= BRILLIANT_MIN_WP and not already_winning(best_cp, second_cp):
        return "Brilliant", "!!"
    if (is_top and not only_legal and not mates_now and second_cp is not None and wp_after >= 40
            and win_pct(best_cp) - win_pct(second_cp) >= GREAT_GAP and win_pct(second_cp) <= GREAT_MAX_SECOND_WP):
        return "Great", "!"
    if is_top or loss <= T_BEST:
        return "Best", "★"
    if loss <= T_EXCELLENT:
        return "Excellent", ""
    if loss <= T_GOOD:
        return "Good", ""
    if loss <= T_INACC:
        return "Inaccuracy", "?!"
    if loss <= T_MISTAKE:
        return "Mistake", "?"
    return "Blunder", "??"


def gives_mate(board, move):
    b = board.copy(stack=False)
    b.push(move)
    return b.is_checkmate()


def evaluate_move(engine, board, move, limit, pre=None):
    """Bewertet einen Zug relativ zu den besten Alternativen. `pre` = vorhandene MultiPV-Infos."""
    me = board.turn
    legal = list(board.legal_moves)
    if pre is None:
        pre = analyse(engine, board, limit, multipv=min(2, len(legal)))
    best_cp = cp_of(pre[0]["score"], me)
    second_cp = cp_of(pre[1]["score"], me) if len(pre) > 1 else None
    top_move = pre[0]["pv"][0]
    if move == top_move:
        played_cp, played_info = best_cp, pre[0]
    else:
        played_info = analyse(engine, board, limit, root_moves=[move])[0]
        played_cp = cp_of(played_info["score"], me)
        # Engine-Rauschen: falls der gespielte Zug tiefer gerechnet besser ist als "bester"
        if played_cp > best_cp:
            best_cp = played_cp
    wp_best, wp_played = win_pct(best_cp), win_pct(played_cp)
    loss = max(0.0, wp_best - wp_played)
    sac, sac_piece = sacrifice_amount(board, move)
    label, sym = classify(loss, move == top_move, sac, wp_played, best_cp, second_cp, len(legal) == 1,
                          gives_mate(board, move))
    return {
        "move_san": board.san(move), "move_uci": move.uci(), "label": label, "symbol": sym,
        "eval": fmt_score(played_info["score"], chess.WHITE), "win_pct": round(wp_played, 1),
        "win_pct_loss": round(loss, 1), "sacrifice_pawns": sac,
        "sacrificed_piece": PIECE_DE.get(sac_piece), "side": "Weiß" if me else "Schwarz",
        "best_move_san": board.san(top_move), "best_eval": fmt_score(pre[0]["score"], chess.WHITE),
        "line": pv_san(board, played_info.get("pv", [move])),
        "best_line": pv_san(board, pre[0].get("pv", [top_move])),
    }


# ---------- Modi ----------

DE_TO_EN = {"S": "N", "L": "B", "T": "R", "D": "Q"}


def de_to_en(tok):
    """Deutsche Figurenbuchstaben (S/L/T/D, auch bei Umwandlung =D) in englische SAN übersetzen."""
    if tok and tok[0] in DE_TO_EN:
        tok = DE_TO_EN[tok[0]] + tok[1:]
    if "=" in tok and tok[tok.index("=") + 1:tok.index("=") + 2] in DE_TO_EN:
        i = tok.index("=") + 1
        tok = tok[:i] + DE_TO_EN[tok[i]] + tok[i + 1:]
    return tok


def parse_move(board, tok):
    for cand in (tok, de_to_en(tok)):
        try:
            return board.parse_san(cand)
        except ValueError:
            pass
    return chess.Move.from_uci(tok)


def build_board(fen, moves):
    board = chess.Board(fen) if fen else chess.Board()
    if moves:
        for tok in moves.replace(",", " ").split():
            if tok.rstrip(".").isdigit() or tok.endswith(".") and tok[:-1].replace(".", "").isdigit():
                continue
            tok = tok.split(".")[-1] if "." in tok else tok
            if tok in ("1-0", "0-1", "1/2-1/2", "*"):
                continue
            board.push(parse_move(board, tok))
    return board


def mode_best(engine, board, args):
    me = board.turn
    if board.is_game_over():
        return {"game_over": True, "result": board.result(), "reason": str(board.outcome().termination.name)}
    limit = chess.engine.Limit(time=args.time, depth=args.depth)
    n = min(args.multipv, board.legal_moves.count())
    infos = analyse(engine, board, limit, multipv=max(n, 2) if board.legal_moves.count() > 1 else 1)
    lines = []
    best_cp = cp_of(infos[0]["score"], me)
    second_cp = cp_of(infos[1]["score"], me) if len(infos) > 1 else None
    for i, inf in enumerate(infos[:n]):
        mv = inf["pv"][0]
        cp = cp_of(inf["score"], me)
        sac, sac_piece = sacrifice_amount(board, mv)
        loss = max(0.0, win_pct(best_cp) - win_pct(cp))
        label, sym = classify(loss, i == 0, sac, win_pct(cp), best_cp, second_cp, board.legal_moves.count() == 1,
                              gives_mate(board, mv))
        lines.append({"rank": i + 1, "move_san": board.san(mv), "move_uci": mv.uci(), "label": label,
                      "symbol": sym, "eval": fmt_score(inf["score"], chess.WHITE), "win_pct": round(win_pct(cp), 1),
                      "sacrifice_pawns": sac, "sacrificed_piece": PIECE_DE.get(sac_piece), "depth": inf.get("depth"), "line": pv_san(board, inf["pv"])})
    # Brilliant-Scan: alle legalen Opferzüge, die nicht schon in den Top-Linien stehen, einzeln prüfen
    brilliants = [l for l in lines if l["label"] == "Brilliant"]
    shown = {l["move_uci"] for l in lines}
    sac_moves = [m for m in board.legal_moves if m.uci() not in shown and sacrifice_amount(board, m)[0]]
    scan_limit = chess.engine.Limit(time=max(0.1, args.time / 3), depth=args.depth)
    for mv in sac_moves[: args.max_sac_scan]:
        inf = analyse(engine, board, scan_limit, root_moves=[mv])[0]
        cp = cp_of(inf["score"], me)
        loss = max(0.0, win_pct(best_cp) - win_pct(cp))
        if loss <= BRILLIANT_MAX_LOSS and win_pct(cp) >= BRILLIANT_MIN_WP and not already_winning(best_cp, second_cp):
            brilliants.append({"move_san": board.san(mv), "move_uci": mv.uci(), "label": "Brilliant", "symbol": "!!",
                               "eval": fmt_score(inf["score"], chess.WHITE), "win_pct": round(win_pct(cp), 1),
                               "sacrifice_pawns": sacrifice_amount(board, mv)[0],
                               "sacrificed_piece": PIECE_DE.get(sacrifice_amount(board, mv)[1]), "line": pv_san(board, inf["pv"]),
                               "note": "nicht in den Top-Linien, aber laut Einzelprüfung (fast) gleichwertig"})
    return {"fen": board.fen(), "side_to_move": "Weiß" if me else "Schwarz", "lines": lines,
            "brilliant_candidates": brilliants, "sacrifices_scanned": len(sac_moves[: args.max_sac_scan])}


def mode_move(engine, board, args):
    tok = args.move
    try:
        mv = parse_move(board, tok)
    except ValueError:
        sys.exit(f"Zug nicht lesbar: {tok}")
    if mv not in board.legal_moves:
        sys.exit(f"Illegaler Zug: {tok}")
    limit = chess.engine.Limit(time=args.time, depth=args.depth)
    r = evaluate_move(engine, board, mv, limit)
    r["fen"] = board.fen()
    return r


def mode_game(engine, args):
    if args.pgn:
        text = open(args.pgn, encoding="utf-8", errors="replace").read() if os.path.exists(args.pgn) else args.pgn
        game = chess.pgn.read_game(io.StringIO(text))
        if game is None:
            sys.exit("PGN konnte nicht gelesen werden.")
        board = game.board()
        moves = list(game.mainline_moves())
        headers = dict(game.headers)
    else:
        start = build_board(args.fen, None)
        tmp = build_board(args.fen, args.moves)
        moves = list(tmp.move_stack)
        board, headers = start, {}
    limit = chess.engine.Limit(time=args.time, depth=args.depth)
    out, stats = [], {"Weiß": {}, "Schwarz": {}}
    losses = {"Weiß": [], "Schwarz": []}
    for mv in moves:
        side = "Weiß" if board.turn else "Schwarz"
        num = board.fullmove_number
        if board.legal_moves.count() == 1:
            r = {"move_san": board.san(mv), "label": "Forced", "symbol": "", "win_pct_loss": 0.0}
        else:
            r = evaluate_move(engine, board, mv, limit)
        r.update({"ply": len(board.move_stack) + 1, "number": num, "side": side})
        out.append(r)
        stats[side][r["label"]] = stats[side].get(r["label"], 0) + 1
        losses[side].append(r["win_pct_loss"])
        board.push(mv)
    # Genauigkeit nach Lichess-Formel aus durchschnittlichem Win%-Verlust
    acc = {s: (round(max(0, min(100, 103.1668 * math.exp(-0.04354 * (sum(l) / len(l))) - 3.1669)), 1) if l else None)
           for s, l in losses.items()}
    term = {"CHECKMATE": "Schachmatt", "STALEMATE": "Patt", "INSUFFICIENT_MATERIAL": "ungenügendes Material",
            "THREEFOLD_REPETITION": "dreifache Wiederholung", "FIVEFOLD_REPETITION": "fünffache Wiederholung",
            "SEVENTYFIVE_MOVES": "75-Züge-Regel"}
    oc = board.outcome()
    return {"headers": headers, "moves": out, "summary": stats, "accuracy": acc,
            "result": oc.result() if oc else headers.get("Result", "*"),
            "termination": term.get(oc.termination.name, oc.termination.name) if oc else None}


# ---------- Textausgabe ----------

def print_text(mode, res):
    if mode == "best":
        if res.get("game_over"):
            print(f"Partie beendet: {res['result']} ({res['reason']})")
            return
        print(f"Am Zug: {res['side_to_move']}    FEN: {res['fen']}\n")
        for l in res["lines"]:
            tag = f" [{l['label']} {l['symbol']}]".rstrip() if l["label"] in ("Brilliant", "Great") else ""
            sac = (f"  (Opfer: {l['sacrificed_piece']}, netto {l['sacrifice_pawns']} Bauerneinheiten)"
                   if l["sacrifice_pawns"] else "")
            print(f"{l['rank']}. {l['move_san']}{l['symbol'] if l['symbol'] in ('!!', '!') else ''}  "
                  f"Bewertung {l['eval']}  (Gewinnchance {res['side_to_move']} {l['win_pct']}%){tag}{sac}")
            print(f"   Linie: {l['line']}   [Tiefe {l['depth']}]")
        b = res["brilliant_candidates"]
        print(f"\nBrilliant-Kandidaten ({res['sacrifices_scanned']} Opferzüge geprüft): " +
              (", ".join(f"{x['move_san']}!! ({x['eval']})" for x in b) if b else "keine"))
        for x in b:
            if x.get("note"):
                print(f"   {x['move_san']}!!: {x['line']}  – {x['note']}")
    elif mode == "move":
        r = res
        print(f"Zug {r['move_san']}: {r['label']} {r['symbol']}  Bewertung {r['eval']} (Gewinnchance {r['side']} {r['win_pct']}%, "
              f"Verlust {r['win_pct_loss']} Pkt.)")
        if r["sacrifice_pawns"]:
            print(f"Opfer: {r['sacrificed_piece']}, netto {r['sacrifice_pawns']} Bauerneinheiten")
        print(f"Linie: {r['line']}")
        print(f"Engine-Bester: {r['best_move_san']} ({r['best_eval']})  Linie: {r['best_line']}")
    else:
        h = res["headers"]
        if h:
            print(f"{h.get('White', '?')} – {h.get('Black', '?')}  {h.get('Result', '')}\n")
        for r in res["moves"]:
            pre = f"{r['number']}." if r["side"] == "Weiß" else f"{r['number']}..."
            extra = ""
            if r["label"] in ("Inaccuracy", "Mistake", "Blunder"):
                extra = f"   besser: {r['best_move_san']} ({r['best_eval']})"
            if r["label"] != "Forced":
                print(f"{pre}{r['move_san']}{r['symbol'] if r['symbol'] != '★' else ''}  {r['label']}  {r.get('eval','')}{extra}")
            else:
                print(f"{pre}{r['move_san']}  Forced")
        print(f"\nErgebnis: {res['result']}" + (f" ({res['termination']})" if res.get("termination") else ""))
        print("Zusammenfassung:")
        for s in ("Weiß", "Schwarz"):
            counts = ", ".join(f"{k}: {v}" for k, v in sorted(res["summary"][s].items()))
            print(f"  {s}: Genauigkeit {res['accuracy'][s]}%  –  {counts}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=["best", "move", "game"])
    ap.add_argument("--fen")
    ap.add_argument("--moves", help='Züge in SAN/UCI, z.B. "e4 e5 Nf3 Nc6" (auch Zugnummern und deutsche Notation Sf3/Lc4)')
    ap.add_argument("--move", help="Zu bewertender Zug (Modus move)")
    ap.add_argument("--pgn", help="PGN-Datei oder PGN-Text (Modus game)")
    ap.add_argument("--time", type=float, default=None, help="Sekunden pro Stellung (Default: best 3, move 2, game 0.4)")
    ap.add_argument("--depth", type=int, default=None, help="Feste Suchtiefe statt/zusätzlich zur Zeit")
    ap.add_argument("--multipv", type=int, default=3)
    ap.add_argument("--max-sac-scan", type=int, default=12)
    ap.add_argument("--threads", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    ap.add_argument("--hash", type=int, default=256, help="Hash in MB")
    ap.add_argument("--engine")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    if args.time is None and args.depth is None:
        args.time = {"best": 3.0, "move": 2.0, "game": 0.4}[args.mode]

    engine = chess.engine.SimpleEngine.popen_uci(find_engine(args.engine))
    try:
        try:
            engine.configure({"Threads": args.threads, "Hash": args.hash})
        except chess.engine.EngineError:
            pass
        if args.mode == "game":
            if not args.pgn and not args.moves:
                sys.exit("Modus game braucht --pgn oder --moves.")
            res = mode_game(engine, args)
        else:
            board = build_board(args.fen, args.moves)
            if args.mode == "best":
                res = mode_best(engine, board, args)
            else:
                if not args.move:
                    sys.exit("Modus move braucht --move.")
                res = mode_move(engine, board, args)
    finally:
        engine.quit()
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        print_text(args.mode, res)


if __name__ == "__main__":
    main()
