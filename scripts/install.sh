#!/usr/bin/env bash
#
# Full install: Python environment, locked dependencies, the Satoshi fonts and
# the compiled UI. Safe to re-run — every step is idempotent, so this doubles as
# the upgrade command after `git pull`.
#
#   ./scripts/install.sh
#   ./scripts/install.sh --no-path    # skip the `opportunity-tracker` command
#
# What it deliberately does NOT do: install Claude Code, create the database, or
# ask for any configuration. The first-run wizard in the app handles all of that.

set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$PWD"

ADD_TO_PATH=1
while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-path) ADD_TO_PATH=0; shift ;;
    -h|--help) sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

BOLD=$'\033[1m'; DIM=$'\033[2m'; RED=$'\033[31m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'; OFF=$'\033[0m'
step() { printf '\n%s==>%s %s%s\n' "$BOLD" "$OFF" "$1" "$OFF"; }
ok()   { printf '    %s✓%s %s\n' "$GREEN" "$OFF" "$1"; }
warn() { printf '    %s!%s %s\n' "$YELLOW" "$OFF" "$1"; }
die()  { printf '\n%serror:%s %s\n\n' "$RED" "$OFF" "$1" >&2; exit 1; }

# --------------------------------------------------------------- requirements

step "Checking what is already installed"

PYTHON=""
for candidate in python3.14 python3.13 python3.12 python3.11 python3; do
  if command -v "$candidate" >/dev/null 2>&1; then
    # 3.11 is the floor: the code uses syntax and stdlib behaviour from it.
    if "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
      PYTHON="$candidate"
      break
    fi
  fi
done
[[ -n "$PYTHON" ]] || die "Python 3.11 or newer is required. Install it, then run this again.
       macOS:  brew install python@3.13
       Debian: sudo apt install python3 python3-venv"
ok "$($PYTHON --version)"

command -v node >/dev/null 2>&1 || die "Node.js is required to build the interface.
       macOS:  brew install node
       Other:  https://nodejs.org/en/download

       Node is needed after installing too: the app serves a compiled bundle, so
       any change to frontend/src — including ones the agent makes — needs a
       rebuild to take effect."
NODE_MAJOR="$(node --version | sed 's/^v\([0-9]*\).*/\1/')"
[[ "$NODE_MAJOR" -ge 18 ]] || die "Node 18 or newer is required (found $(node --version))."
ok "Node $(node --version), npm $(npm --version)"

command -v git >/dev/null 2>&1 \
  && ok "git $(git --version | awk '{print $3}')" \
  || warn "git not found — the agent's undo history will be unavailable"

# Claude Code is a runtime dependency, not a build one. The setup wizard asks for
# the path if it is not on PATH, so this is a heads-up rather than a failure.
if command -v claude >/dev/null 2>&1; then
  ok "Claude Code $(claude --version 2>/dev/null | head -1)"
else
  warn "claude CLI not on PATH — install it from https://claude.com/claude-code"
  warn "the setup wizard will ask you for its location on first run"
fi

# ---------------------------------------------------------- python environment

step "Python environment"

if [[ ! -x .venv/bin/python ]]; then
  "$PYTHON" -m venv .venv
  ok "created .venv"
else
  ok "reusing .venv"
fi

# uv resolves and installs the same locked versions an order of magnitude faster
# when it happens to be present. Neither path is required by the other.
if command -v uv >/dev/null 2>&1; then
  uv pip install --quiet --python .venv/bin/python -r requirements.txt
  ok "dependencies installed with uv"
else
  .venv/bin/python -m pip install --quiet --upgrade pip
  .venv/bin/python -m pip install --quiet -r requirements.txt
  ok "dependencies installed"
fi

# ------------------------------------------------------------------- the fonts

step "Fonts"

FONT_DIR="frontend/public/fonts"
FONT_URL="https://api.fontshare.com/v2/fonts/download/satoshi"
mkdir -p "$FONT_DIR"

if [[ -f "$FONT_DIR/Satoshi-Variable.woff2" && -f "$FONT_DIR/Satoshi-VariableItalic.woff2" ]]; then
  ok "Satoshi already present"
else
  # Satoshi is not in the repository. Its licence permits self-hosting but not
  # redistribution, so each install fetches its own copy and is its own
  # licensee. Missing fonts are not fatal — the CSS falls back to system-ui.
  printf '    fetching Satoshi from Fontshare (ITF Free Font License)\n'
  TMP="$(mktemp -d)"
  trap 'rm -rf "$TMP"' EXIT
  if curl -fsSL --max-time 120 "$FONT_URL" -o "$TMP/satoshi.zip" \
     && unzip -qo "$TMP/satoshi.zip" -d "$TMP/unpacked" 2>/dev/null; then
    found=0
    while IFS= read -r file; do
      cp "$file" "$FONT_DIR/" && found=$((found + 1))
    done < <(find "$TMP/unpacked" -name 'Satoshi-Variable.woff2' -o -name 'Satoshi-VariableItalic.woff2')
    license_file="$(find "$TMP/unpacked" -iname 'FFL.txt' -o -iname 'LICENSE*.txt' | head -1)"
    [[ -n "$license_file" ]] && cp "$license_file" "$FONT_DIR/LICENSE.txt"
    if [[ "$found" -ge 2 ]]; then
      ok "Satoshi installed ($found files)"
    else
      warn "font archive did not contain the expected files — using system fonts"
    fi
  else
    warn "could not download Satoshi — the app will use system fonts instead"
    warn "to add it later: re-run this script, or download from fontshare.com/fonts/satoshi"
  fi
  rm -rf "$TMP"
  trap - EXIT
fi

# --------------------------------------------------------------------- the UI

step "Interface"

cd frontend
if [[ -f package-lock.json ]]; then
  npm ci --silent
else
  # No lockfile means this is not a clean checkout; install and create one.
  npm install --silent
fi
ok "node modules installed"

# Vite's chunk-size advisory goes to stderr on every successful build; showing
# it here reads like something went wrong. Keep the output for a real failure.
if ! BUILD_LOG="$(npm run build 2>&1)"; then
  printf '%s\n' "$BUILD_LOG" >&2
  die "the interface failed to build"
fi
[[ -f dist/index.html ]] || die "the interface build produced no dist/index.html"
ok "interface built into frontend/dist"
cd "$ROOT"

# ------------------------------------------------------------------ config file

step "Configuration"

if [[ ! -f .env && -f .env.example ]]; then
  cp .env.example .env
  ok "created .env from .env.example"
else
  ok ".env already present"
fi

mkdir -p data logs
ok "data/ and logs/ ready"

# ------------------------------------------------------------------- the command

step "Command"

BIN_DIR="$HOME/.local/bin"
LAUNCHER="$BIN_DIR/opportunity-tracker"
MARKER="# Added by Opportunity Tracker (scripts/install.sh)"

if [[ "$ADD_TO_PATH" == 0 ]]; then
  ok "skipped (--no-path); start it with ./scripts/start.sh"
else
  mkdir -p "$BIN_DIR"

  # A wrapper, not a symlink: start.sh locates the project with
  # `dirname "$0"`, which through a symlink would resolve to ~/.local/bin and
  # send it looking for the app one directory above that.
  cat > "$LAUNCHER" <<LAUNCHER_EOF
#!/usr/bin/env bash
# Opportunity Tracker launcher, generated by scripts/install.sh.
# Delete this file to remove the command.
PROJECT="$ROOT"
if [[ ! -x "\$PROJECT/scripts/start.sh" ]]; then
  echo "opportunity-tracker: the app is no longer at \$PROJECT" >&2
  echo "Re-run ./scripts/install.sh from wherever it lives now, or delete \$0" >&2
  exit 1
fi
exec "\$PROJECT/scripts/start.sh" "\$@"
LAUNCHER_EOF
  chmod +x "$LAUNCHER"
  ok "installed $LAUNCHER"

  # Warn rather than shadow: another command by this name already on PATH and
  # found first would make the new one look broken.
  CLASH="$(command -v opportunity-tracker 2>/dev/null || true)"
  if [[ -n "$CLASH" && "$CLASH" != "$LAUNCHER" ]]; then
    warn "another 'opportunity-tracker' is earlier on your PATH: $CLASH"
  fi

  if [[ ":$PATH:" == *":$BIN_DIR:"* ]]; then
    ok "$BIN_DIR is already on your PATH"
  else
    # Only the config for the shell actually in use is touched, and only once.
    SHELL_NAME="$(basename "${SHELL:-}")"
    case "$SHELL_NAME" in
      zsh)  RC="$HOME/.zshrc";  LINE="export PATH=\"\$HOME/.local/bin:\$PATH\"" ;;
      bash) RC="$HOME/.bashrc"; LINE="export PATH=\"\$HOME/.local/bin:\$PATH\"" ;;
      fish) RC="$HOME/.config/fish/config.fish"; LINE="fish_add_path \$HOME/.local/bin" ;;
      *)    RC="$HOME/.profile"; LINE="export PATH=\"\$HOME/.local/bin:\$PATH\"" ;;
    esac

    if [[ -f "$RC" ]] && grep -qF "$MARKER" "$RC"; then
      ok "$RC already updated"
    else
      mkdir -p "$(dirname "$RC")"
      printf '\n%s\n%s\n' "$MARKER" "$LINE" >> "$RC"
      ok "added $BIN_DIR to your PATH in $RC"
      warn "open a new terminal (or: source $RC) before the command works"
    fi
  fi
fi

# ----------------------------------------------------------------------- done

cat <<BANNER

${GREEN}${BOLD}Installed.${OFF}

  Start it:   ${BOLD}opportunity-tracker${OFF}   (or ${BOLD}./scripts/start.sh${OFF})
  Then open:  ${BOLD}http://localhost:8000${OFF}

${DIM}Development instead? ./scripts/dev.sh runs the API with a Vite dev server on
:5173, so frontend edits hot-reload without a rebuild.${OFF}
BANNER