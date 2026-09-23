#!/usr/bin/env bash
# Build distributable artifacts for aisle-cli into ./dist:
#   * aisle.pyz   - a zero-install single-file zipapp (run: python3 aisle.pyz)
#   * a pip wheel + sdist (if the 'build' module is available)
#   * aisle-cli-src.zip - a clean source archive
#
# Usage: ./build.sh
set -euo pipefail
cd "$(dirname "$0")"

DIST=dist
rm -rf "$DIST" build *.egg-info
mkdir -p "$DIST"

# The standard-library modules that make up the runtime (not the tests).
RUNTIME=(aisle.py aisle_cli.py aisle_tui.py aisle_store.py \
         aisle_aisleriot.py aisle_camo.py)

# ---- 1. zipapp: a single runnable .pyz, no install needed -------------------
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
cp "${RUNTIME[@]}" "$STAGE"/
cat > "$STAGE/__main__.py" <<'PY'
import sys
from aisle_cli import main
sys.exit(main())
PY
python3 -m zipapp "$STAGE" -p "/usr/bin/env python3" -o "$DIST/aisle.pyz"
chmod +x "$DIST/aisle.pyz"
echo "built $DIST/aisle.pyz"

# ---- 2. wheel + sdist (pip-installable) -------------------------------------
if python3 -c "import build" 2>/dev/null; then
    python3 -m build --outdir "$DIST" .
    echo "built wheel + sdist in $DIST/"
else
    echo "note: 'python3 -m build' unavailable; skipping wheel/sdist."
    echo "      install it with:  pip install build   then re-run ./build.sh"
fi

# ---- 3. clean source archive ------------------------------------------------
SRCZIP="$DIST/aisle-cli-src.zip"
zip -qr "$SRCZIP" "${RUNTIME[@]}" tests \
    README.md LICENSE pyproject.toml build.sh -x '*__pycache__*'
echo "built $SRCZIP"

echo
echo "Artifacts in $DIST/:"
ls -1 "$DIST"
