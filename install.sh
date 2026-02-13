#!/bin/bash
set -euo pipefail

# ============================================================================
# Reaper Installer
# Clones reaper and installs via uv tool (editable)
# ============================================================================

# --- Colors (Rich-inspired palette) ---
readonly CYAN='\033[0;36m'
readonly GREEN='\033[0;32m'
readonly YELLOW='\033[0;33m'
readonly RED='\033[0;31m'
readonly DIM='\033[2m'
readonly BOLD='\033[1m'
readonly NC='\033[0m'

# --- Configuration ---
readonly REPO_URL="https://github.com/daviguides/reaper.git"
readonly INSTALL_DIR="$HOME/.local/share/reaper"
readonly VERSION="0.1.0"
readonly CRON_MARKER="# crony:reaper"
readonly CRON_JOB="*/15 * * * * /bin/zsh -l -c 'reaper hunt -y' $CRON_MARKER"

# --- Box width (53 chars between borders) ---
readonly W=53

# --- UI Helpers ---
box_top() {
  printf "${CYAN}╭"
  printf '─%.0s' $(seq 1 $W)
  printf "╮${NC}\n"
}

box_bottom() {
  printf "${CYAN}╰"
  printf '─%.0s' $(seq 1 $W)
  printf "╯${NC}\n"
}

box_empty() {
  printf "${CYAN}│${NC}%${W}s${CYAN}│${NC}\n" ""
}

box_separator() {
  printf "${CYAN}│${DIM}"
  printf '─%.0s' $(seq 1 $W)
  printf "${NC}${CYAN}│${NC}\n"
}

box_text() {
  local text="$1"
  local len=${#text}
  local pad=$((W - 2 - len))
  printf "${CYAN}│${NC}  %s%${pad}s${CYAN}│${NC}\n" "$text" ""
}

status_line() {
  local icon="$1"
  local color="$2"
  local text="$3"
  local len=${#text}
  local pad=$((W - 4 - len))
  printf "${CYAN}│${NC}  ${color}%s${NC} %s%${pad}s${CYAN}│${NC}\n" "$icon" "$text" ""
}

status_ok() { status_line "✓" "$GREEN" "$1"; }
status_warn() { status_line "⚠" "$YELLOW" "$1"; }
status_error() { status_line "✗" "$RED" "$1"; }
status_info() { status_line "→" "$DIM" "$1"; }

spinner() {
  local pid=$1
  local msg="$2"
  local len=${#msg}
  local pad=$((W - 4 - len))
  local spin='⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏'
  local i=0
  while kill -0 "$pid" 2>/dev/null; do
    printf "\r${CYAN}│${NC}  ${CYAN}%s${NC} %s%${pad}s${CYAN}│${NC}" "${spin:i++%10:1}" "$msg" ""
    sleep 0.1
  done
  printf "\r%*s\r" 60 ""
}

# --- Cleanup on error ---
cleanup_on_error() {
  if [ "${INSTALL_FAILED:-}" = "1" ] && [ -d "$INSTALL_DIR" ]; then
    rm -rf "$INSTALL_DIR"
  fi
}
trap cleanup_on_error EXIT

# ============================================================================
# Functions
# ============================================================================

print_header() {
  printf "\n"
  box_top
  box_empty
  printf "${CYAN}│${NC}   ${BOLD}reaper${NC}     Orphan Process Hunter             ${CYAN}│${NC}\n"
  printf "${CYAN}│${NC}              for Claude Code (v${VERSION})            ${CYAN}│${NC}\n"
  box_empty
  box_separator
}

check_dependencies() {
  local missing=0

  if ! command -v git >/dev/null 2>&1; then
    status_error "git is not installed"
    box_text "Install: https://git-scm.com/downloads"
    missing=1
  else
    status_ok "git found"
  fi

  if ! command -v uv >/dev/null 2>&1; then
    status_error "uv is not installed"
    box_text "Install: curl -LsSf https://astral.sh/uv/install.sh | sh"
    missing=1
  else
    status_ok "uv found"
  fi

  if [ "$missing" -eq 1 ]; then
    box_empty
    box_bottom
    printf "\n"
    exit 1
  fi
}

clone_repository() {
  if [ -d "$INSTALL_DIR" ]; then
    status_info "Updating existing installation..."
    git -C "$INSTALL_DIR" pull --quiet 2>/dev/null &
    local pid=$!
    spinner $pid "Pulling latest changes..."
    wait $pid || {
      status_warn "Pull failed, re-cloning..."
      rm -rf "$INSTALL_DIR"
      clone_fresh
      return
    }
    status_ok "Repository updated"
  else
    clone_fresh
  fi
}

clone_fresh() {
  INSTALL_FAILED=1
  mkdir -p "$(dirname "$INSTALL_DIR")"
  git clone --quiet "$REPO_URL" "$INSTALL_DIR" 2>/dev/null &
  local pid=$!
  spinner $pid "Cloning repository..."
  wait $pid || {
    status_error "Failed to clone repository"
    box_empty
    box_bottom
    printf "\n"
    exit 1
  }
  INSTALL_FAILED=0
  status_ok "Repository cloned to ~/.local/share/reaper"
}

validate_structure() {
  if [ ! -f "$INSTALL_DIR/pyproject.toml" ]; then
    status_error "Invalid repository structure"
    INSTALL_FAILED=1
    exit 1
  fi
}

install_tool() {
  uv tool install -e "$INSTALL_DIR" 2>/dev/null &
  local pid=$!
  spinner $pid "Installing reaper via uv tool..."
  wait $pid || {
    # Retry with --force in case of previous install
    uv tool install --force -e "$INSTALL_DIR" 2>/dev/null &
    pid=$!
    spinner $pid "Reinstalling reaper..."
    wait $pid || {
      status_error "Failed to install reaper"
      box_empty
      box_bottom
      printf "\n"
      exit 1
    }
  }
  status_ok "reaper installed (editable)"
}

verify_install() {
  if command -v reaper >/dev/null 2>&1; then
    status_ok "reaper command available"
  else
    status_warn "reaper not in PATH"
    box_text "Add to your shell profile:"
    box_text "  export PATH=\"\$HOME/.local/bin:\$PATH\""
  fi
}

setup_cron() {
  if crontab -l 2>/dev/null | grep -qF "$CRON_MARKER"; then
    # Replace existing entry (handles upgrades)
    local current_cron
    current_cron=$(crontab -l 2>/dev/null | grep -vF "$CRON_MARKER")
    printf '%s\n%s\n' "$current_cron" "$CRON_JOB" | crontab -
    status_ok "Cron job updated (every 15 min)"
  else
    # Add new entry
    (crontab -l 2>/dev/null; printf '%s\n' "$CRON_JOB") | crontab -
    status_ok "Cron job added (every 15 min)"
  fi
}

print_complete() {
  box_empty
  box_separator
  printf "${CYAN}│${NC}  ${GREEN}${BOLD}Installation Complete${NC}                              ${CYAN}│${NC}\n"
  box_separator
  box_empty
  printf "${CYAN}│${NC}  ${BOLD}Usage${NC}                                              ${CYAN}│${NC}\n"
  box_text "reaper list              # Show Claude processes"
  box_text "reaper hunt -y           # Kill orphans"
  box_empty
  printf "${CYAN}│${NC}  ${BOLD}Cron${NC}                                               ${CYAN}│${NC}\n"
  box_text "Runs every 15 min: reaper hunt -y"
  box_text "Check: crontab -l | grep reaper"
  box_empty
  printf "${CYAN}│${NC}  ${BOLD}Update${NC}                                             ${CYAN}│${NC}\n"
  box_text "Re-run this installer or:"
  box_text "cd ~/.local/share/reaper && git pull"
  box_empty
  box_bottom
  printf "\n"
}

# ============================================================================
# Main
# ============================================================================

main() {
  print_header
  check_dependencies
  clone_repository
  validate_structure
  install_tool
  verify_install
  setup_cron
  print_complete
}

main
