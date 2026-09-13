#!/usr/bin/env bash
# ==============================================================================
# Desktop TimeTracker Installer for KDE Plasma 6 Wayland
# ==============================================================================

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${BLUE}==>${NC} Installing Desktop TimeTracker..."

# 1. Dependency checks
echo -e "${BLUE}==>${NC} Checking system dependencies..."
missing_deps=()

if ! command -v python3 >/dev/null 2>&1; then
    missing_deps+=("python3")
fi

if ! command -v qdbus6 >/dev/null 2>&1; then
    missing_deps+=("qdbus6 (usually in package 'qt6-tools')")
fi

if ! command -v systemctl >/dev/null 2>&1; then
    missing_deps+=("systemd")
fi

if [ ${#missing_deps[@]} -gt 0 ]; then
    echo -e "${RED}Error: Missing required dependencies:${NC}"
    for dep in "${missing_deps[@]}"; do
        echo -e "  - ${dep}"
    done
    echo -e "${YELLOW}On Arch Linux, install with: sudo pacman -S python qt6-tools${NC}"
    exit 1
fi

# 2. Target Directories
BIN_DIR="${HOME}/.local/bin"
DATA_DIR="${HOME}/.local/share/timetracker"
CONFIG_DIR="${HOME}/.config/timetracker"
SYSTEMD_DIR="${HOME}/.config/systemd/user"
REPORTS_DIR="${HOME}/Documents/TimeReports"

mkdir -p "${BIN_DIR}" "${DATA_DIR}" "${CONFIG_DIR}" "${SYSTEMD_DIR}" "${REPORTS_DIR}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 3. Copy files
echo -e "${BLUE}==>${NC} Deploying binaries and scripts..."
install -m 755 "${SCRIPT_DIR}/src/desktop-timetracker" "${BIN_DIR}/desktop-timetracker"
ln -sf "${BIN_DIR}/desktop-timetracker" "${BIN_DIR}/timetrack"

install -m 644 "${SCRIPT_DIR}/src/timetracker_kwin.js" "${DATA_DIR}/timetracker_kwin.js"

if [ ! -f "${CONFIG_DIR}/rules.json" ]; then
    echo -e "${BLUE}==>${NC} Initializing default rules..."
    install -m 644 "${SCRIPT_DIR}/config/rules.json.example" "${CONFIG_DIR}/rules.json"
else
    echo -e "${YELLOW}==>${NC} Existing rules.json found; skipping overwrite."
fi

# 4. Configure systemd service
echo -e "${BLUE}==>${NC} Configuring systemd user service..."
install -m 644 "${SCRIPT_DIR}/systemd/desktop-timetracker.service" "${SYSTEMD_DIR}/desktop-timetracker.service"

systemctl --user daemon-reload
systemctl --user enable --now desktop-timetracker.service

echo ""
echo -e "${GREEN}======================================================${NC}"
echo -e "${GREEN}  Desktop TimeTracker installed and started!          ${NC}"
echo -e "${GREEN}======================================================${NC}"
echo ""
echo -e "Try these commands in your terminal:"
echo -e "  ${YELLOW}timetrack today${NC}    - View today's screen time report"
echo -e "  ${YELLOW}timetrack week${NC}     - View past 7 days trend"
echo -e "  ${YELLOW}timetrack status${NC}   - Check daemon status & active window"
echo -e "  ${YELLOW}timetrack export${NC}   - Export today's Markdown report"
echo ""
