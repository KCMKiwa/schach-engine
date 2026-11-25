#!/usr/bin/env bash
# Installiert Stockfish und python-chess, falls sie fehlen. Idempotent.
set -e
if ! command -v stockfish >/dev/null 2>&1 && [ ! -x /usr/games/stockfish ] && [ -z "$STOCKFISH_PATH" ]; then
  if command -v apt-get >/dev/null 2>&1; then
    (apt-get install -y stockfish >/dev/null 2>&1 || (apt-get update >/dev/null 2>&1 && apt-get install -y stockfish >/dev/null 2>&1)) || true
  elif command -v brew >/dev/null 2>&1; then
    brew install stockfish >/dev/null 2>&1 || true
  fi
fi
if ! python3 -c "import chess" >/dev/null 2>&1; then
  pip install chess >/dev/null 2>&1 || {
    # Fallback: Quellpaket direkt kopieren (reines Python, kein Build nötig)
    tmp=$(mktemp -d)
    pip download chess --no-deps --no-binary :all: -d "$tmp" >/dev/null 2>&1 || pip download chess --no-deps -d "$tmp" >/dev/null 2>&1
    cd "$tmp" && tar xzf chess-*.tar.gz 2>/dev/null || true
    site=$(python3 -c "import site;print(site.getsitepackages()[0])")
    cp -r "$tmp"/chess-*/chess "$site/"
  }
fi
python3 -c "import chess; print('python-chess', chess.__version__)"
(command -v stockfish || ls /usr/games/stockfish || echo "$STOCKFISH_PATH") 2>/dev/null | head -1 | sed 's/^/stockfish: /'
