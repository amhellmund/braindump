#!/usr/bin/env bash
# build.sh — Package braindump into a standalone Tauri desktop app.
#
# What this script does, in order:
#   1. Checks for required tools (uv, npm, cargo, rustc).
#   2. Builds the React frontend (frontend/dist/).
#   3. Bundles the Python backend into a single binary via PyInstaller.
#   4. Copies the binary into src-tauri/binaries/ with the correct
#      Rust target-triple suffix that Tauri's sidecar mechanism requires.
#   5. Generates app icons from frontend/src/assets/logo.png.
#   6. Runs `cargo tauri build` to produce the final app bundle.
#
# Output:
#   macOS: tauri_app/src-tauri/target/release/bundle/dmg/braindump_*.dmg
#          tauri_app/src-tauri/target/release/bundle/macos/braindump.app
#   Linux: tauri_app/src-tauri/target/release/bundle/deb/*.deb
#          tauri_app/src-tauri/target/release/bundle/appimage/*.AppImage
#   Windows: tauri_app/src-tauri/target/release/bundle/msi/*.msi
#
# Usage:
#   cd <repo-root>/tauri_app && ./build.sh
#   OR from anywhere:
#   /path/to/tauri_app/build.sh
#
# Environment variables:
#   SKIP_FRONTEND_BUILD=1   Skip `npm run build` (useful if already built).
#   SKIP_PYINSTALLER=1      Skip PyInstaller (useful when binary already exists).

set -eo pipefail

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TAURI_SRC="$SCRIPT_DIR/src-tauri"
BINARIES_DIR="$TAURI_SRC/binaries"
PY_DIST_DIR="$SCRIPT_DIR/.dist-py"
PY_WORK_DIR="$SCRIPT_DIR/.pyinstaller-work"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

info()  { echo "==> $*"; }
warn()  { echo "WARN: $*" >&2; }
abort() { echo "ERROR: $*" >&2; exit 1; }

require_cmd() {
    command -v "$1" >/dev/null 2>&1 || abort "'$1' not found. $2"
}

# ---------------------------------------------------------------------------
# 1. Prerequisite checks
# ---------------------------------------------------------------------------

info "Checking prerequisites…"

require_cmd uv    "Install from https://docs.astral.sh/uv/getting-started/installation/"
require_cmd npm   "Install Node.js from https://nodejs.org/"
require_cmd cargo "Install Rust from https://rustup.rs/"
require_cmd rustc "Install Rust from https://rustup.rs/"

# Tauri v2 needs Rust >= 1.77
RUST_VERSION=$(rustc --version | awk '{print $2}')
info "Rust version: $RUST_VERSION"

# ---------------------------------------------------------------------------
# 2. Detect Rust target triple (used for sidecar binary naming)
# ---------------------------------------------------------------------------

RUST_TARGET=$(rustc -vV | grep '^host:' | awk '{print $2}')
info "Rust target triple: $RUST_TARGET"

SIDECAR_BIN="$BINARIES_DIR/braindump-$RUST_TARGET"

# ---------------------------------------------------------------------------
# 3. Build the React frontend
# ---------------------------------------------------------------------------

if [[ "${SKIP_FRONTEND_BUILD:-0}" == "1" ]]; then
    warn "Skipping frontend build (SKIP_FRONTEND_BUILD=1)"
    [[ -d "$REPO_ROOT/frontend/dist" ]] || abort "frontend/dist not found. Run without SKIP_FRONTEND_BUILD=1 first."
else
    info "Building React frontend…"
    cd "$REPO_ROOT/frontend"
    npm install --silent
    npm run build
    cd "$REPO_ROOT"
    info "Frontend built → frontend/dist/"
fi

# ---------------------------------------------------------------------------
# 4. Bundle the Python backend with PyInstaller
# ---------------------------------------------------------------------------

if [[ "${SKIP_PYINSTALLER:-0}" == "1" ]]; then
    warn "Skipping PyInstaller (SKIP_PYINSTALLER=1)"
    [[ -f "$PY_DIST_DIR/braindump" ]] || abort ".dist-py/braindump not found. Run without SKIP_PYINSTALLER=1 first."
else
    info "Bundling Python backend with PyInstaller…"
    info "  This may take several minutes on the first run."

    cd "$REPO_ROOT"

    # Install the project itself and PyInstaller into the uv-managed venv.
    uv sync --quiet
    uv pip install --quiet pyinstaller

    uv run pyinstaller \
        --onefile \
        --name braindump \
        --add-data "frontend/dist:braindump/frontend/dist" \
        --collect-all braindump \
        --collect-all uvicorn \
        --collect-all fastapi \
        --collect-all mistune \
        --collect-all frontmatter \
        --collect-all claude_agent_sdk \
        --hidden-import uvicorn.loops.auto \
        --hidden-import uvicorn.loops.asyncio \
        --hidden-import uvicorn.lifespan.on \
        --hidden-import uvicorn.protocols.http.auto \
        --hidden-import uvicorn.protocols.http.h11_impl \
        --hidden-import uvicorn.protocols.websockets.auto \
        --hidden-import uvicorn.protocols.websockets.websockets_impl \
        --distpath "$PY_DIST_DIR" \
        --workpath "$PY_WORK_DIR" \
        --specpath "$REPO_ROOT" \
        --noconfirm \
        "$SCRIPT_DIR/braindump_entry.py"

    info "PyInstaller bundle → $PY_DIST_DIR/braindump"
fi

# ---------------------------------------------------------------------------
# 5. Copy sidecar binary into src-tauri/binaries/ with target-triple suffix
# ---------------------------------------------------------------------------

info "Installing sidecar binary as braindump-$RUST_TARGET…"
mkdir -p "$BINARIES_DIR"
cp "$PY_DIST_DIR/braindump" "$SIDECAR_BIN"
chmod +x "$SIDECAR_BIN"
info "Sidecar ready → $SIDECAR_BIN"

# ---------------------------------------------------------------------------
# 6. Generate app icons from the braindump logo
# ---------------------------------------------------------------------------

LOGO="$REPO_ROOT/frontend/src/assets/logo.png"

if [[ -f "$LOGO" ]]; then
    info "Generating app icons from logo.png…"

    # tauri icon requires a square source image.
    # Pad the logo to a square canvas (transparent background) using Pillow.
    SQUARED_LOGO="$PY_WORK_DIR/logo_square.png"
    mkdir -p "$PY_WORK_DIR"
    uv run --with pillow python3 - "$LOGO" "$SQUARED_LOGO" <<'PYEOF'
import sys
from PIL import Image
img = Image.open(sys.argv[1]).convert("RGBA")
w, h = img.size
size = max(w, h)
canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
canvas.paste(img, ((size - w) // 2, (size - h) // 2))
canvas.save(sys.argv[2])
print(f"  Padded logo to {size}×{size}")
PYEOF

    cd "$SCRIPT_DIR"
    # Install Tauri CLI locally if not already present.
    npm install --silent
    # `tauri icon` generates all required sizes (32x32, 128x128, 128x128@2x, .icns, .ico).
    npx --yes @tauri-apps/cli@^2 icon "$SQUARED_LOGO" --output "$TAURI_SRC/icons"
    info "Icons written → src-tauri/icons/"
else
    warn "logo.png not found at $LOGO — skipping icon generation."
    warn "Tauri will use placeholder icons if src-tauri/icons/ is empty."
fi

# ---------------------------------------------------------------------------
# 7. Build the Tauri app
# ---------------------------------------------------------------------------

info "Building Tauri app (cargo tauri build)…"
cd "$SCRIPT_DIR"
npm install --silent
npx @tauri-apps/cli@^2 build

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------

info "Build complete!"
echo ""
echo "  App bundle:"

BUNDLE_DIR="$TAURI_SRC/target/release/bundle"

if [[ "$(uname)" == "Darwin" ]]; then
    echo "    DMG:  $BUNDLE_DIR/dmg/"
    echo "    .app: $BUNDLE_DIR/macos/braindump.app"
elif [[ "$(uname)" == "Linux" ]]; then
    echo "    .deb:      $BUNDLE_DIR/deb/"
    echo "    AppImage:  $BUNDLE_DIR/appimage/"
else
    echo "    MSI: $BUNDLE_DIR/msi/"
fi

echo ""
echo "  Note: The app uses the Claude Code credentials in ~/.claude/ for AI features."
echo "        Run \`claude login\` once if you haven't already."
echo ""
echo "  Workspace default: ~/braindump-workspace"
echo "  Override:          BRAINDUMP_TAURI_WORKSPACE=/path/to/workspace ./braindump"
