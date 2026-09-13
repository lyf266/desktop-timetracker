#!/usr/bin/env bash
# ==============================================================================
# Desktop TimeTracker Uninstaller
# ==============================================================================

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

PURGE=false
if [[ "${1:-}" == "--purge" ]]; then
    PURGE=true
fi

echo -e "${BLUE}==>${NC} Stopping and disabling systemd service..."
systemctl --user stop desktop-timetracker.service 2>/dev/null || true
systemctl --user disable desktop-timetracker.service 2>/dev/null || true

echo -e "${BLUE}==>${NC} Removing binaries and service units..."
rm -f "${HOME}/.local/bin/desktop-timetracker"
rm -f "${HOME}/.local/bin/timetrack"
rm -f "${HOME}/.local/share/timetracker/timetracker_kwin.js"
rm -f "${HOME}/.config/systemd/user/desktop-timetracker.service"

systemctl --user daemon-reload

if [ "${PURGE}" = true ]; then
    echo -e "${YELLOW}==>${NC} Purging database and configurations (--purge specified)..."
    rm -rf "${HOME}/.local/share/timetracker"
    rm -rf "${HOME}/.config/timetracker"
    echo -e "${GREEN}All data, configs, and binaries purged.${NC}"
else
    echo -e "${GREEN}==>${NC} Binaries and service removed."
    echo -e "${BLUE}Note: Database (~/.local/share/timetracker/timetracker.db) and reports (~/Documents/TimeReports/) were preserved.${NC}"
    echo -e "To purge all data, re-run with: ${YELLOW}./uninstall.sh --purge${NC}"
fi

echo -e "${GREEN}Desktop TimeTracker successfully uninstalled.${NC}"
