#!/usr/bin/env bash
# Build a clean, store-ready zip (module folder at zip root).
# Usage: scripts/build_store_zip.sh
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"
MODULE_NAME="$(ls -d */__manifest__.py 2>/dev/null | head -1 | cut -d/ -f1)"
[ -n "$MODULE_NAME" ] || {
    echo "no module folder with __manifest__.py found" >&2
    exit 1
}
VERSION="$(python3 -c "import ast; print(ast.literal_eval(open('$MODULE_NAME/__manifest__.py').read())['version'])")"
mkdir -p dist
ZIP="dist/${MODULE_NAME}-${VERSION}.zip"
rm -f "$ZIP"
zip -r -q "$ZIP" "$MODULE_NAME" \
    -x "*__pycache__*" "*.pyc" "*.DS_Store" "${MODULE_NAME}/dist/*"
echo "Built: $ZIP ($(du -h "$ZIP" | cut -f1))"
unzip -l "$ZIP" | head -6
