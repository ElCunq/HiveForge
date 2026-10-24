#!/usr/bin/env bash
# ==============================================================================
# AGY-VIBE / SYM-VIBE UNINSTALLER
# ==============================================================================
set -e

COLOR_RESET="\033[0m"
COLOR_GREEN="\033[1;32m"
COLOR_AMBER="\033[1;33m"
COLOR_RED="\033[1;31m"

INSTALL_BIN_DIR="$HOME/.local/bin"
SYSTEMD_USER_DIR="$HOME/.config/systemd/user"
SERVICE_FILE="$SYSTEMD_USER_DIR/agy-vibe.service"
BASE_DIR="${AGY_TEAMS_DIR:-$HOME/.agy-teams}"

echo -e "${COLOR_AMBER}>>> AGY-Vibe / Sym-Vibe Kaldırma Aracı <<<${COLOR_RESET}\n"

# 1. Systemd servisini durdur ve kaldır
if [ -f "$SERVICE_FILE" ]; then
  echo -e "• Systemd servisi durduruluyor ve kaldırılıyor..."
  systemctl --user stop agy-vibe.service 2>/dev/null || true
  systemctl --user disable agy-vibe.service 2>/dev/null || true
  rm -f "$SERVICE_FILE"
  systemctl --user daemon-reload 2>/dev/null || true
  echo -e "  ${COLOR_GREEN}✓ Servis kaldırıldı.${COLOR_RESET}"
fi

# 2. Çalışan python server sürecini sonlandır
echo -e "• Arka plan sunucu süreçleri temizleniyor..."
fuser -k 4444/tcp 2>/dev/null || true

# 3. Sembolik bağları sil
echo -e "• CLI kısayolları kaldırılıyor..."
rm -f "$INSTALL_BIN_DIR/team" "$INSTALL_BIN_DIR/agy-team"
echo -e "  ${COLOR_GREEN}✓ $INSTALL_BIN_DIR/team ve agy-team silindi.${COLOR_RESET}"

# 4. Veritabanı ve durum dosyaları
if [ -d "$BASE_DIR" ]; then
  if [ "$1" = "--purge" ]; then
    rm -rf "$BASE_DIR"
    echo -e "  ${COLOR_GREEN}✓ $BASE_DIR veritabanı ve takımları temizlendi (--purge).${COLOR_RESET}"
  else
    echo -e "  ${COLOR_AMBER}• Takım veritabanı ($BASE_DIR) korundu.${COLOR_RESET} (Tamamen silmek için: $0 --purge)"
  fi
fi

echo -e "\n${COLOR_GREEN}AGY-Vibe başarıyla kaldırıldı.${COLOR_RESET}\n"
