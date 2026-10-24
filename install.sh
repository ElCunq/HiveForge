#!/usr/bin/env bash
# ==============================================================================
# HIVEFORGE v3.5 - UNIVERSAL INSTALLER & OS-AWARE SETUP WIZARD
# Multi-CLI Autonomous Agent Team Cockpit & Orchestrator
# Compatible with: agy, claude, codex, aider, ollama, custom runtimes
# Supports: Linux (Arch, Debian/Ubuntu, Fedora, Alpine, WSL), macOS (Darwin)
# ==============================================================================
set -e

COLOR_RESET="\033[0m"
COLOR_GREEN="\033[1;32m"
COLOR_AMBER="\033[1;33m"
COLOR_CYAN="\033[1;36m"
COLOR_GRAY="\033[90m"
COLOR_RED="\033[1;31m"
COLOR_BOLD="\033[1m"

SCRIPT_DIR="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_PATH="$SCRIPT_DIR/bin/team"
INSTALL_BIN_DIR="$HOME/.local/bin"
DEFAULT_PORT=4444

echo -e "${COLOR_AMBER}"
cat << 'EOF'
  ___ ___ .__            ___________                             
 /   |   \|__|__  ______ \_   _____/___________  ____   ____     
/    ~    \  \  \/ /\__  \|    __) /  _ \_  __ \/ ___\_/ __ \    
\    Y    /  |\   /  / __ \|     \(  <_> )  | \/ /_/  >  ___/    
 \___|_  /|__| \_/  (____  /\___  / \____/|__|  \___  / \___  >   
       \/                \/     \/             /_____/      \/   
  Autonomous Multi-Agent Mission Control & Multi-CLI Orchestrator
EOF
echo -e "${COLOR_RESET}"
echo -e "${COLOR_CYAN}>>> HiveForge Ortam ve Sistem Kurulum Sihirbazı <<<${COLOR_RESET}\n"

# ----------------- 1. GELİŞMİŞ OS VE DAĞITIM ALGILAMA -----------------
echo -e "${COLOR_GRAY}[1/6] İşletim Sistemi ve Ortam Algılanıyor...${COLOR_RESET}"
OS_TYPE="$(uname -s)"
OS_ARCH="$(uname -m)"
DISTRO_NAME="Bilinmiyor"
PKG_MANAGER="none"
IS_WSL=false

if [ "$OS_TYPE" = "Linux" ]; then
  if grep -qi "microsoft" /proc/version 2>/dev/null; then
    IS_WSL=true
  fi

  if [ -f /etc/os-release ]; then
    # shellcheck disable=SC1091
    . /etc/os-release
    DISTRO_NAME="${PRETTY_NAME:-$NAME}"
    DISTRO_ID="${ID:-linux}"
    case "$DISTRO_ID" in
      arch|manjaro|cachyos|endeavouros)
        PKG_MANAGER="pacman"
        PKG_INSTALL_CMD="sudo pacman -S --needed python python-pip tmux"
        ;;
      ubuntu|debian|pop|mint|elementary)
        PKG_MANAGER="apt"
        PKG_INSTALL_CMD="sudo apt update && sudo apt install -y python3 python3-pip tmux"
        ;;
      fedora|rhel|centos|rocky|alma)
        PKG_MANAGER="dnf"
        PKG_INSTALL_CMD="sudo dnf install -y python3 python3-pip tmux"
        ;;
      opensuse*|suse)
        PKG_MANAGER="zypper"
        PKG_INSTALL_CMD="sudo zypper install -y python3 python3-pip tmux"
        ;;
      alpine)
        PKG_MANAGER="apk"
        PKG_INSTALL_CMD="apk add --no-cache python3 py3-pip tmux bash"
        ;;
      *)
        PKG_MANAGER="generic-linux"
        PKG_INSTALL_CMD="Paket yöneticinizle python3 ve tmux kurun."
        ;;
    esac
  fi
  echo -e "      İşletim Sistemi: ${COLOR_GREEN}Linux (${DISTRO_NAME})${COLOR_RESET} [${OS_ARCH}]"
  if [ "$IS_WSL" = true ]; then
    echo -e "      Çalışma Ortamı:  ${COLOR_AMBER}Windows Subsystem for Linux (WSL)${COLOR_RESET}"
  fi

elif [ "$OS_TYPE" = "Darwin" ]; then
  DISTRO_NAME="macOS $(sw_vers -productVersion 2>/dev/null || '')"
  PKG_MANAGER="brew"
  PKG_INSTALL_CMD="brew install python tmux"
  echo -e "      İşletim Sistemi: ${COLOR_GREEN}${DISTRO_NAME}${COLOR_RESET} [${OS_ARCH}]"

else
  echo -e "      İşletim Sistemi: ${COLOR_AMBER}${OS_TYPE} (${OS_ARCH})${COLOR_RESET}"
fi

# ----------------- 2. PYTHON VE BAĞIMLILIK KONTROLÜ -----------------
echo -e "\n${COLOR_GRAY}[2/6] Python ve Kütüphane Kontrolü...${COLOR_RESET}"
if ! command -v python3 >/dev/null 2>&1; then
  echo -e "${COLOR_RED}[HATA] python3 bulunamadı!${COLOR_RESET}"
  echo -e "      Lütfen şu komutla kurun: ${COLOR_CYAN}${PKG_INSTALL_CMD}${COLOR_RESET}"
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

# ----------------- 3. ÇOKLU CLI AJAN MOTORLARI TARAMASI -----------------
echo -e "\n${COLOR_GRAY}[3/6] Desteklenen Çoklu CLI Ajan Motorları Taraması...${COLOR_RESET}"
check_tool() {
  local tool_cmd="$1"
  local name="$2"
  local hint="$3"
  if command -v "$tool_cmd" >/dev/null 2>&1; then
    local p
    p=$(command -v "$tool_cmd")
    echo -e "      • ${name} (${tool_cmd}): ${COLOR_GREEN}✓ Algılandı${COLOR_RESET} (${COLOR_GRAY}${p}${COLOR_RESET})"
  else
    echo -e "      • ${name} (${tool_cmd}): ${COLOR_GRAY}○ Yüklü Değil (${hint})${COLOR_RESET}"
  fi
}

check_tool "agy"    "Google Antigravity"     "curl -sSL https://antigravity.google/install | bash"
check_tool "claude" "Anthropic Claude Code"  "npm install -g @anthropic-ai/claude-code"
check_tool "codex"  "OpenAI Codex CLI"       "npm install -g @openai/codex veya openai cli"
check_tool "aider"  "Aider CLI"              "pip install aider-chat"
check_tool "ollama" "Ollama Local LLM"       "curl -fsSL https://ollama.com/install.sh | sh"
check_tool "tmux"   "Tmux Terminal Multiplex" "${PKG_INSTALL_CMD}"

# ----------------- 4. PORT VE AĞ YAPILANDIRMASI -----------------
echo -e "\n${COLOR_GRAY}[4/6] Web Kokpit Portu...${COLOR_RESET}"
PORT="${HIVE_PORT:-${AGY_PORT:-$DEFAULT_PORT}}"
if [ -t 0 ] && [ "$1" != "-y" ] && [ "$1" != "--yes" ]; then
  read -r -p "      Web Arayüzü Portu [$PORT]: " USER_PORT
  if [ -n "$USER_PORT" ]; then
    PORT="$USER_PORT"
  fi
fi
echo -e "      Port seçildi: ${COLOR_GREEN}${PORT}${COLOR_RESET}"

# ----------------- 5. CLI KISAYOLLARI (SYMLINKS) -----------------
echo -e "\n${COLOR_GRAY}[5/6] CLI Kısayolları (~/.local/bin/hive & team)...${COLOR_RESET}"
mkdir -p "$INSTALL_BIN_DIR"
chmod +x "$BIN_PATH"

ln -sf "$BIN_PATH" "$INSTALL_BIN_DIR/hive"
ln -sf "$BIN_PATH" "$INSTALL_BIN_DIR/team"
ln -sf "$BIN_PATH" "$INSTALL_BIN_DIR/cortex"
ln -sf "$BIN_PATH" "$INSTALL_BIN_DIR/agy-team"

echo -e "      ${COLOR_GREEN}✓${COLOR_RESET} $INSTALL_BIN_DIR/hive -> $BIN_PATH"
echo -e "      ${COLOR_GREEN}✓${COLOR_RESET} $INSTALL_BIN_DIR/team -> $BIN_PATH"
echo -e "      ${COLOR_GREEN}✓${COLOR_RESET} $INSTALL_BIN_DIR/cortex -> $BIN_PATH"

# PATH kontrolü
if [[ ":$PATH:" != *":$INSTALL_BIN_DIR:"* ]]; then
  echo -e "      ${COLOR_AMBER}[BİLGİ] $INSTALL_BIN_DIR PATH değişkeninizde yer almıyor.${COLOR_RESET}"
  echo -e "      Terminalinize kalıcı eklemek için:"
  echo -e "      ${COLOR_CYAN}echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.bashrc${COLOR_RESET} (veya ~/.zshrc)"
fi

# ----------------- 6. OS'A ÖZEL SERVİS ENTEGRASYONU -----------------
echo -e "\n${COLOR_GRAY}[6/6] İşletim Sistemine Göre Arka Plan Servis Yapılandırması...${COLOR_RESET}"

if [ "$OS_TYPE" = "Darwin" ]; then
  # macOS LaunchAgent (~/Library/LaunchAgents)
  LAUNCH_DIR="$HOME/Library/LaunchAgents"
  PLIST_FILE="$LAUNCH_DIR/com.hiveforge.orchestrator.plist"
  mkdir -p "$LAUNCH_DIR"

  cat > "$PLIST_FILE" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.hiveforge.orchestrator</string>
    <key>ProgramArguments</key>
    <array>
        <string>$(command -v python3)</string>
        <string>$SCRIPT_DIR/server.py</string>
        <string>$PORT</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$SCRIPT_DIR</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/tmp/hiveforge.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/hiveforge.err</string>
</dict>
</plist>
EOF
  launchctl unload "$PLIST_FILE" 2>/dev/null || true
  launchctl load "$PLIST_FILE" 2>/dev/null || true
  echo -e "      ${COLOR_GREEN}✓${COLOR_RESET} macOS LaunchAgent servisi aktif: $PLIST_FILE"

elif [ "$OS_TYPE" = "Linux" ] && command -v systemctl >/dev/null 2>&1 && [ -d /run/user/$(id -u) ]; then
  # Linux Systemd User Daemon
  SYSTEMD_USER_DIR="$HOME/.config/systemd/user"
  SERVICE_FILE="$SYSTEMD_USER_DIR/hiveforge.service"
  mkdir -p "$SYSTEMD_USER_DIR"

  cat > "$SERVICE_FILE" << EOF
[Unit]
Description=HiveForge Autonomous Multi-Agent Web & Native Orchestrator
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

  # Legacy compatibility symlink
  ln -sf "$SERVICE_FILE" "$SYSTEMD_USER_DIR/agy-vibe.service"

  systemctl --user daemon-reload
  systemctl --user enable hiveforge.service >/dev/null 2>&1 || true
  systemctl --user restart hiveforge.service >/dev/null 2>&1 || true
  echo -e "      ${COLOR_GREEN}✓${COLOR_RESET} Linux Systemd servisi aktif: hiveforge.service (Port $PORT)"

else
  # Generic Linux / WSL fallback without systemd
  echo -e "      ${COLOR_AMBER}• Systemd bus bulunamadı, arka plan nohup daemon kullanılacak.${COLOR_RESET}"
fi

# ----------------- KURULUM TAMAMLANDI -----------------
echo -e "\n${COLOR_GREEN}================================================================${COLOR_RESET}"
echo -e "${COLOR_GREEN}  HIVEFORGE v3.5 KURULUMU BAŞARIYLA TAMAMLANDI!${COLOR_RESET}"
echo -e "${COLOR_GREEN}================================================================${COLOR_RESET}"
echo -e "Desteklenen Komutlar:"
echo -e "  • Web Kokpiti Aç:      ${COLOR_CYAN}hive${COLOR_RESET} veya ${COLOR_CYAN}team${COLOR_RESET} (Tarayıcı: http://127.0.0.1:$PORT)"
echo -e "  • Terminal Tmux Modu:  ${COLOR_CYAN}hive tmux${COLOR_RESET} veya ${COLOR_CYAN}team tmux${COLOR_RESET}"
echo -e "  • Ajan Listesi & CLI:  ${COLOR_CYAN}hive agents${COLOR_RESET}"
echo -e "  • Doğrudan Terminal:   ${COLOR_CYAN}hive open @backend${COLOR_RESET}"
echo -e "  • Yardım & Menü:       ${COLOR_CYAN}hive help${COLOR_RESET}"
echo -e "================================================================\n"
