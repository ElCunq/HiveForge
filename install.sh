#!/usr/bin/env bash
# ==============================================================================
# AGY-VIBE / SYM-VIBE INSTALLER & SETUP WIZARD
# Multi-CLI Autonomous Multi-Agent Orchestrator
# ==============================================================================
set -e

COLOR_RESET="\033[0m"
COLOR_GREEN="\033[1;32m"
COLOR_AMBER="\033[1;33m"
COLOR_CYAN="\033[1;36m"
COLOR_GRAY="\033[90m"
COLOR_RED="\033[1;31m"

SCRIPT_DIR="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_PATH="$SCRIPT_DIR/bin/team"
INSTALL_BIN_DIR="$HOME/.local/bin"
DEFAULT_PORT=4444

echo -e "${COLOR_AMBER}"
cat << 'EOF'
   _____   _______     __ __      _____ ____  ______ 
  /  _  \ / ____\ \   / //  \    /  _  \\______ \    
 /  /_\  \\   __\ \  / //    \  /  /_\  \|    |  \   
/    |    \|  |    \/ //  /\  \/    |    \    `   \  
\____|__  /|__|    / / \__/\  /\____|__  /_______  / 
        \/        / /       \/         \/        \/  
  Autonomous Multi-Agent Mission Control & Orchestrator
EOF
echo -e "${COLOR_RESET}"
echo -e "${COLOR_CYAN}>>> AGY-Vibe / Sym-Vibe Kurulum ve Ortam Sihirbazı<<<${COLOR_RESET}\n"

# 1. Python 3 Kontrolü
echo -e "${COLOR_GRAY}[1/5] Python ve Bağımlılık Kontrolü...${COLOR_RESET}"
if ! command -v python3 >/dev/null 2>&1; then
  echo -e "${COLOR_RED}[HATA] python3 bulunamadı! Lütfen Python 3.9+ kurun.${COLOR_RESET}"
  exit 1
fi

PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo -e "      Python Sürümü: ${COLOR_GREEN}${PY_VER}${COLOR_RESET}"

# aiohttp Kontrolü
if ! python3 -c "import aiohttp" >/dev/null 2>&1; then
  echo -e "      ${COLOR_AMBER}[UYARI] aiohttp bulunamadı. Kuruluyor...${COLOR_RESET}"
  python3 -m pip install -r "$SCRIPT_DIR/requirements.txt" || {
    echo -e "${COLOR_RED}[HATA] 'pip install aiohttp' başarısız oldu. Lütfen manuel kurun: pip install aiohttp${COLOR_RESET}"
    exit 1
  }
else
  echo -e "      aiohttp: ${COLOR_GREEN}Yüklü${COLOR_RESET}"
fi

# 2. Desteklenen CLI Motorlarını Algıla
echo -e "\n${COLOR_GRAY}[2/5] CLI Ajan Motorları Taraması...${COLOR_RESET}"
check_tool() {
  local tool_cmd="$1"
  local name="$2"
  if command -v "$tool_cmd" >/dev/null 2>&1; then
    local p
    p=$(command -v "$tool_cmd")
    echo -e "      • ${name} (${tool_cmd}): ${COLOR_GREEN}✓ Algılandı${COLOR_RESET} (${COLOR_GRAY}${p}${COLOR_RESET})"
  else
    echo -e "      • ${name} (${tool_cmd}): ${COLOR_GRAY}○ Yüklü Değil (Opsiyonel)${COLOR_RESET}"
  fi
}

check_tool "agy" "Google Antigravity"
check_tool "claude" "Anthropic Claude Code"
check_tool "aider" "Aider CLI"
check_tool "ollama" "Ollama Local LLM"
check_tool "tmux" "Tmux Terminal Multiplexer"

# 3. Port Yapılandırması
echo -e "\n${COLOR_GRAY}[3/5] Web Kokpit Portu...${COLOR_RESET}"
PORT="${AGY_PORT:-$DEFAULT_PORT}"
if [ -t 0 ] && [ "$1" != "-y" ] && [ "$1" != "--yes" ]; then
  read -r -p "      Web Arayüzü Portu [$PORT]: " USER_PORT
  if [ -n "$USER_PORT" ]; then
    PORT="$USER_PORT"
  fi
fi
echo -e "      Port seçildi: ${COLOR_GREEN}${PORT}${COLOR_RESET}"

# 4. CLI Sembolik Bağları (~/.local/bin)
echo -e "\n${COLOR_GRAY}[4/5] CLI Kısayolu (~/.local/bin/team)...${COLOR_RESET}"
mkdir -p "$INSTALL_BIN_DIR"
chmod +x "$BIN_PATH"
ln -sf "$BIN_PATH" "$INSTALL_BIN_DIR/team"
ln -sf "$BIN_PATH" "$INSTALL_BIN_DIR/agy-team"
echo -e "      ${COLOR_GREEN}✓${COLOR_RESET} $INSTALL_BIN_DIR/team -> $BIN_PATH"
echo -e "      ${COLOR_GREEN}✓${COLOR_RESET} $INSTALL_BIN_DIR/agy-team -> $BIN_PATH"

# PATH kontrolü
if [[ ":$PATH:" != *":$INSTALL_BIN_DIR:"* ]]; then
  echo -e "      ${COLOR_AMBER}[BİLGİ] $INSTALL_BIN_DIR PATH değişkeninizde yer almıyor.${COLOR_RESET}"
  echo -e "      Terminalinize eklemek için: ${COLOR_CYAN}export PATH=\"\$HOME/.local/bin:\$PATH\"${COLOR_RESET}"
fi

# 5. Systemd Kullanıcı Servisi
echo -e "\n${COLOR_GRAY}[5/5] Arka Plan Servisi (Systemd User Daemon)...${COLOR_RESET}"
SYSTEMD_USER_DIR="$HOME/.config/systemd/user"
SERVICE_FILE="$SYSTEMD_USER_DIR/agy-vibe.service"

if command -v systemctl >/dev/null 2>&1 && [ -d /run/user/$(id -u) ]; then
  mkdir -p "$SYSTEMD_USER_DIR"
  cat > "$SERVICE_FILE" << EOF
[Unit]
Description=AGY-Vibe / Sym-Vibe Multi-Agent Web & Native Orchestrator
After=network.target

[Service]
Type=simple
WorkingDirectory=$SCRIPT_DIR
ExecStart=$(command -v python3) $SCRIPT_DIR/server.py $PORT
Restart=always
RestartSec=3
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=default.target
EOF

  systemctl --user daemon-reload
  systemctl --user enable agy-vibe.service >/dev/null 2>&1 || true
  systemctl --user restart agy-vibe.service >/dev/null 2>&1 || true
  echo -e "      ${COLOR_GREEN}✓${COLOR_RESET} Systemd servisi aktif: agy-vibe.service (Port $PORT)"
else
  echo -e "      ${COLOR_GRAY}○ Systemd user bus bulunamadı, servis manuel nohup ile çalışacak.${COLOR_RESET}"
fi

# Kurulum Tamamlandı
echo -e "\n${COLOR_GREEN}================================================================${COLOR_RESET}"
echo -e "${COLOR_GREEN}  KURULUM BAŞARIYLA TAMAMLANDI!${COLOR_RESET}"
echo -e "${COLOR_GREEN}================================================================${COLOR_RESET}"
echo -e "Hemen Başlamak İçin:"
echo -e "  • Web Kokpiti Aç:      ${COLOR_CYAN}team${COLOR_RESET} (veya tarayıcıda: http://127.0.0.1:$PORT)"
echo -e "  • Terminal Tmux Modu:  ${COLOR_CYAN}team tmux${COLOR_RESET}"
echo -e "  • Takım Durumu:        ${COLOR_CYAN}team agents${COLOR_RESET}"
echo -e "  • Yardım Menüsü:       ${COLOR_CYAN}team help${COLOR_RESET}"
echo -e "================================================================\n"
