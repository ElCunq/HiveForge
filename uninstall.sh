#!/usr/bin/env bash
# ==============================================================================
# HIVEFORGE UNINSTALLER
# ==============================================================================
set -e

COLOR_RESET="\033[0m"
COLOR_GREEN="\033[1;32m"
COLOR_AMBER="\033[1;33m"
COLOR_RED="\033[1;31m"

INSTALL_BIN_DIR="$HOME/.local/bin"
SYSTEMD_USER_DIR="$HOME/.config/systemd/user"
SERVICE_FILE="$SYSTEMD_USER_DIR/hiveforge.service"
LEGACY_SERVICE="$SYSTEMD_USER_DIR/agy-vibe.service"
MAC_PLIST="$HOME/Library/LaunchAgents/com.hiveforge.orchestrator.plist"
BASE_DIR="${HIVE_TEAMS_DIR:-${AGY_TEAMS_DIR:-$HOME/.agy-teams}}"

echo -e "${COLOR_AMBER}>>> HiveForge Kaldırma Aracı <<<${COLOR_RESET}\n"

# 1. Systemd / LaunchAgent servisini durdur ve kaldır
if command -v systemctl >/dev/null 2>&1; then
  echo -e "• Linux Systemd servisi durduruluyor ve kaldırılıyor..."
  systemctl --user stop hiveforge.service agy-vibe.service 2>/dev/null || true
  systemctl --user disable hiveforge.service agy-vibe.service 2>/dev/null || true
  rm -f "$SERVICE_FILE" "$LEGACY_SERVICE"
  systemctl --user daemon-reload 2>/dev/null || true
  echo -e "  ${COLOR_GREEN}✓ Systemd servisi kaldırıldı.${COLOR_RESET}"
fi

if [ -f "$MAC_PLIST" ]; then
  echo -e "• macOS LaunchAgent servisi kaldırılıyor..."
  launchctl unload "$MAC_PLIST" 2>/dev/null || true
  rm -f "$MAC_PLIST"
  echo -e "  ${COLOR_GREEN}✓ LaunchAgent kaldırıldı.${COLOR_RESET}"
fi

# 2. Çalışan python server süreçlerini sonlandır
echo -e "• Arka plan dinleyici süreçleri temizleniyor (Port 4444)..."
fuser -k 4444/tcp 2>/dev/null || true

# 3. Sembolik bağları sil
echo -e "• CLI kısayolları kaldırılıyor..."
rm -f "$INSTALL_BIN_DIR/hive" "$INSTALL_BIN_DIR/team" "$INSTALL_BIN_DIR/cortex" "$INSTALL_BIN_DIR/agy-team"
echo -e "  ${COLOR_GREEN}✓ CLI kısayolları silindi.${COLOR_RESET}"

# 4. Veritabanı ve durum dosyaları
if [ -d "$BASE_DIR" ]; then
  if [ "$1" = "--purge" ]; then
    rm -rf "$BASE_DIR"
    echo -e "  ${COLOR_GREEN}✓ $BASE_DIR veritabanı ve takımları temizlendi (--purge).${COLOR_RESET}"
  else
    echo -e "  ${COLOR_AMBER}• Takım veritabanı ($BASE_DIR) korundu.${COLOR_RESET} (Tamamen silmek için: $0 --purge)"
  fi
fi

echo -e "\n${COLOR_GREEN}HiveForge başarıyla kaldırıldı.${COLOR_RESET}\n"
