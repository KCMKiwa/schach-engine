#!/usr/bin/env bash
# Installiert Stockfish und python-chess, falls sie fehlen. Idempotent.
# Läuft unter Linux, macOS und Windows (Git Bash).
set -e
cd "$(dirname "$0")"   # python-chess liegt mitgeliefert im Ordner chess/

# Python finden (unter Windows heißt es oft "python" oder "py")
PY=""
for c in python3 python py; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c "import sys; sys.exit(sys.version_info < (3, 8))" >/dev/null 2>&1; then
    PY="$c"; break
  fi
done
if [ -z "$PY" ]; then
  echo "Python 3.8+ nicht gefunden. Bitte installieren: https://www.python.org/downloads/"
  exit 1
fi

case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*) WINDOWS=1 ;;
  *) WINDOWS=0 ;;
esac

# python-chess
if ! "$PY" -c "import chess" >/dev/null 2>&1; then
  if [ "$WINDOWS" = 0 ] && command -v apt-get >/dev/null 2>&1; then
    # Debian/Ubuntu/WSL: Systempaket (pip fehlt dort oft oder ist "externally managed")
    sudo apt-get install -y python3-chess || (sudo apt-get update && sudo apt-get install -y python3-chess) || true
  fi
  if ! "$PY" -c "import chess" >/dev/null 2>&1; then
    "$PY" -m pip install --user chess || {
      echo "python-chess konnte nicht installiert werden. Versuche: sudo apt-get install -y python3-pip && $PY -m pip install --user chess"
      exit 1
    }
  fi
fi
"$PY" -c "import chess; print('python-chess', chess.__version__)"

# Stockfish
if [ -n "$STOCKFISH_PATH" ] || command -v stockfish >/dev/null 2>&1 || [ -x /usr/games/stockfish ]; then
  :
elif [ "$WINDOWS" = 1 ]; then
  if command -v winget >/dev/null 2>&1; then
    winget install --accept-package-agreements --accept-source-agreements -e --name Stockfish || true
  fi
elif command -v apt-get >/dev/null 2>&1; then
  sudo apt-get install -y stockfish || (sudo apt-get update && sudo apt-get install -y stockfish) || true
elif command -v brew >/dev/null 2>&1; then
  brew install stockfish || true
fi

SF="${STOCKFISH_PATH:-$(command -v stockfish 2>/dev/null || ls /usr/games/stockfish 2>/dev/null || true)}"
if [ -n "$SF" ]; then
  echo "stockfish: $SF"
  echo
  echo "Fertig. Starten mit:  $PY server.py   und dann http://localhost:8000 öffnen."
else
  echo
  echo "Stockfish wurde nicht gefunden."
  echo "1. Herunterladen: https://stockfishchess.org/download/"
  echo "2. Den Pfad zur stockfish-Datei angeben, z.B. (Git Bash):"
  echo "     export STOCKFISH_PATH=\"/c/Tools/stockfish/stockfish-windows-x86-64-avx2.exe\""
  echo "   oder beim Start:  $PY server.py --engine \"C:\\Tools\\stockfish\\stockfish.exe\""
  exit 1
fi
