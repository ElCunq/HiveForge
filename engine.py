#!/usr/bin/env python3
"""
AGY-VIBE Multi-Agent Orchestrator (Universal Multi-CLI Engine):
- Multi-CLI Runtime Support: Google Antigravity (`agy`), Anthropic (`claude`), `aider`, `ollama` (Local LLM), and Custom Scripts
- SQLite Atomic State Store (~/.agy-teams/state.db)
- Dual Snapshot Engine: Native Brain JSONL (agy) + SQLite Agent Turns (claude/aider/ollama/custom)
- Extensible Tool, Skill, Persona & MCP Hub
- 100% Portable (Zero hardcoded user paths)
"""

import os
import re
import sys
import json
import time
import uuid
import sqlite3
import asyncio
import subprocess
import shutil
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple

def _dir_is_writable(path: Path) -> bool:
    """Klasörü oluşturabiliyor/yazabiliyor muyuz? (Windows'ta kısıtlı profil klasörleri için)"""
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / f".write-test-{os.getpid()}"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def _windows_fallback_root() -> Path:
    return Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")) / "HiveForge"


def _default_base_dir() -> Path:
    if os.environ.get("AGY_TEAMS_DIR"):
        return Path(os.environ["AGY_TEAMS_DIR"])
    home_dir = Path.home() / ".agy-teams"
    if os.name == "nt" and not _dir_is_writable(home_dir):
        return _windows_fallback_root() / "agy-teams"
    return home_dir


def default_projects_root() -> Path:
    """Takım proje dizini verilmediğinde kullanılacak kök (Linux/macOS: ~/agy-teams)."""
    root = Path.home() / "agy-teams"
    if os.name == "nt" and not _dir_is_writable(root):
        return _windows_fallback_root() / "projects"
    return root


# Portable environment-based directories
BASE_DIR = _default_base_dir()
TEAMS_DIR = BASE_DIR / "teams"
DB_PATH = BASE_DIR / "state.db"
BRAIN_DIR = Path.home() / ".gemini" / "antigravity-cli" / "brain"
PROJECT_ROOT = Path(__file__).resolve().parent

BASE_DIR.mkdir(parents=True, exist_ok=True)
TEAMS_DIR.mkdir(parents=True, exist_ok=True)

# Active async subprocess tasks keyed by f"{team}:{target}"
ACTIVE_PROCESSES: Dict[str, asyncio.subprocess.Process] = {}
ACTIVE_TASKS_META: Dict[str, Dict[str, Any]] = {}


# ----------------- Windows Compatibility Layer -----------------
# Linux/macOS davranışı değişmez: aşağıdaki yardımcılar yalnızca os.name == "nt" iken devreye girer.

IS_WINDOWS = os.name == "nt"


def _windows_git_bash() -> Optional[str]:
    """Git for Windows ile gelen bash.exe yolunu bulur (WSL'in System32\\bash.exe'sini atlar)."""
    candidates = []
    git_exe = shutil.which("git")
    if git_exe:
        git_root = Path(git_exe).resolve().parent.parent  # ...\Git\cmd\git.exe -> ...\Git
        candidates += [git_root / "bin" / "bash.exe", git_root / "usr" / "bin" / "bash.exe"]
    for env in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)", "LOCALAPPDATA"):
        base = os.environ.get(env)
        if base:
            candidates.append(Path(base) / "Git" / "bin" / "bash.exe")
            candidates.append(Path(base) / "Programs" / "Git" / "bin" / "bash.exe")
    for c in candidates:
        if c.exists():
            return str(c)
    return None


def _flatten_for_cmd(arg: str) -> str:
    """cmd.exe satır sonlarında komutu keser; yeni satırları boşluğa çevirir."""
    return " ".join(arg.splitlines())


def resolve_cli_command(cmd: List[str]) -> List[str]:
    """
    Windows'ta npm ile kurulan CLI'lar (claude.cmd, codex.cmd ...) CreateProcess ile doğrudan
    başlatılamaz. Bu fonksiyon:
      1. .exe ise tam yolu kullanır,
      2. npm .cmd shim'i ise içindeki node betiğini bulup `node <script>` olarak çalıştırır
         (çok satırlı prompt'lar bozulmadan iletilir),
      3. aksi halde cmd.exe /c üzerinden çalıştırır.
    Linux/macOS'ta komutu olduğu gibi döndürür.
    """
    if not IS_WINDOWS or not cmd:
        return cmd
    exe = shutil.which(cmd[0])
    if not exe:
        return cmd
    ext = Path(exe).suffix.lower()
    if ext in (".exe", ".com"):
        return [exe, *cmd[1:]]
    if ext in (".cmd", ".bat"):
        shim_dir = Path(exe).parent
        try:
            text = Path(exe).read_text(encoding="utf-8", errors="ignore")
            for m in re.finditer(r'"%(?:~dp0|dp0)%\\?([^"%]+?\.(?:js|mjs|cjs|exe))"', text, re.IGNORECASE):
                target = (shim_dir / m.group(1)).resolve()
                if not target.exists():
                    continue
                if target.suffix.lower() == ".exe":
                    return [str(target), *cmd[1:]]
                node = shim_dir / "node.exe"
                node_exe = str(node) if node.exists() else shutil.which("node")
                if node_exe:
                    return [node_exe, str(target), *cmd[1:]]
        except Exception:
            pass
        comspec = os.environ.get("COMSPEC", "cmd.exe")
        return [comspec, "/d", "/s", "/c", exe, *[_flatten_for_cmd(a) for a in cmd[1:]]]
    return [exe, *cmd[1:]]


async def create_shell_subprocess(command: str, cwd: str) -> asyncio.subprocess.Process:
    """Kabuk aracı çalıştırır. Windows'ta varsa Git Bash kullanılır (|, tail, head vb. çalışsın diye)."""
    if IS_WINDOWS:
        bash = _windows_git_bash()
        if bash:
            return await asyncio.create_subprocess_exec(
                bash, "-lc", command,
                cwd=cwd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
    return await asyncio.create_subprocess_shell(
        command,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), timeout=15.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def init_db() -> None:
    with get_db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS teams (
            name TEXT PRIMARY KEY,
            project_dir TEXT NOT NULL,
            session_name TEXT,
            lead_role TEXT DEFAULT 'Tech Lead & Architect',
            lead_cid TEXT DEFAULT '',
            lead_runtime TEXT DEFAULT 'agy',
            lead_persona TEXT DEFAULT '',
            lead_effort TEXT DEFAULT 'high',
            created_at TEXT
        );

        CREATE TABLE IF NOT EXISTS agents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            team_name TEXT NOT NULL,
            aid INTEGER NOT NULL,
            name TEXT NOT NULL,
            role TEXT NOT NULL,
            target TEXT NOT NULL,
            runtime TEXT DEFAULT 'agy',
            model TEXT DEFAULT '',
            cid TEXT DEFAULT '',
            persona TEXT DEFAULT '',
            effort TEXT DEFAULT 'medium',
            mode TEXT DEFAULT 'auto',
            workspace_dir TEXT DEFAULT '',
            skills_json TEXT DEFAULT '[]',
            tools_json TEXT DEFAULT '[]',
            pane INTEGER DEFAULT 0,
            created_at TEXT,
            UNIQUE(team_name, target)
        );

        CREATE TABLE IF NOT EXISTS agent_turns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            team_name TEXT NOT NULL,
            target TEXT NOT NULL,
            runtime TEXT NOT NULL,
            user_prompt TEXT NOT NULL,
            response_md TEXT NOT NULL,
            thinking TEXT DEFAULT '',
            tool_calls_json TEXT DEFAULT '[]',
            command_logs TEXT DEFAULT '',
            status TEXT DEFAULT 'DONE',
            created_at TEXT
        );

        CREATE TABLE IF NOT EXISTS tools_registry (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            description TEXT NOT NULL,
            tool_type TEXT NOT NULL,
            command_or_prompt TEXT NOT NULL,
            icon TEXT DEFAULT '⚡',
            is_builtin INTEGER DEFAULT 0,
            created_at TEXT
        );

        CREATE TABLE IF NOT EXISTS dispatch_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            team_name TEXT NOT NULL,
            target TEXT NOT NULL,
            sender TEXT DEFAULT 'User',
            msg_type TEXT DEFAULT 'dispatch',
            message TEXT NOT NULL,
            status TEXT DEFAULT 'completed',
            result_preview TEXT DEFAULT '',
            created_at TEXT
        );
        """)

        # Add new columns if migrating from an older DB version
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(agents);")
        agent_cols = [c[1] for c in cursor.fetchall()]
        if "runtime" not in agent_cols:
            cursor.execute("ALTER TABLE agents ADD COLUMN runtime TEXT DEFAULT 'agy';")
        if "model" not in agent_cols:
            cursor.execute("ALTER TABLE agents ADD COLUMN model TEXT DEFAULT '';")

        cursor.execute("PRAGMA table_info(teams);")
        team_cols = [c[1] for c in cursor.fetchall()]
        if "lead_runtime" not in team_cols:
            cursor.execute("ALTER TABLE teams ADD COLUMN lead_runtime TEXT DEFAULT 'agy';")

        cursor.execute("PRAGMA table_info(agent_turns);")
        turn_cols = [c[1] for c in cursor.fetchall()]
        if "input_tokens" not in turn_cols:
            cursor.execute("ALTER TABLE agent_turns ADD COLUMN input_tokens INTEGER DEFAULT 0;")
        if "output_tokens" not in turn_cols:
            cursor.execute("ALTER TABLE agent_turns ADD COLUMN output_tokens INTEGER DEFAULT 0;")
        if "total_tokens" not in turn_cols:
            cursor.execute("ALTER TABLE agent_turns ADD COLUMN total_tokens INTEGER DEFAULT 0;")

        seed_builtin_tools(conn)


def seed_builtin_tools(conn: sqlite3.Connection) -> None:
    builtin_tools = [
        (
            "git-status-diff",
            "Git Durum & Diff Analizi",
            "vcs",
            "Çalışma dizinindeki son değişiklikleri, branch durumunu ve diff özetini çıkarır.",
            "shell_context",
            "git status -sb && echo '--- DIFF STAT ---' && git diff --stat",
            "🌿",
            1,
        ),
        (
            "graphify-query",
            "Graphify Mimari Güncelleme",
            "architecture",
            "Kod tabanının Graphify bilgi grafiğini (AST) günceller ve mimari düğümleri doğrular.",
            "shell_context",
            "graphify update . 2>&1 || echo 'Graphify tamamlandı'",
            "🕸️",
            1,
        ),
        (
            "rust-cargo-check",
            "Rust Cargo Check",
            "build",
            "Rust projelerinde (Backend / Wasm / Desktop) hızlı derleme ve tip kontrolü yapar.",
            "shell_context",
            "cargo check --message-format=short 2>&1 | tail -n 35",
            "🦀",
            1,
        ),
        (
            "ts-typecheck",
            "TypeScript & Next.js Kontrolü",
            "build",
            "Web ve Mobil projelerde TypeScript tip hatalarını (tsc --noEmit) tarar.",
            "shell_context",
            "npx tsc --noEmit --pretty false 2>&1 | head -n 35",
            "📘",
            1,
        ),
        (
            "skill-security-audit",
            "OWASP & Güvenlik Denetimi",
            "security",
            "Ajanı security-audit yeteneği ile çalıştırarak son kodlarda güvenlik açığı tarar.",
            "prompt_template",
            "[ARAÇ: security-audit] Üzerinde çalıştığın modüldeki son değişiklikleri OWASP Top 10, yetkilendirme, XSS/Injection ve veri sızıntısı açısından denetle ve bulguları raporla.",
            "🛡️",
            1,
        ),
        (
            "skill-ponytail-simplify",
            "Ponytail Kod Sadeleştirme",
            "quality",
            "Gereksiz karmaşıklığı, ölü kodları ve aşırı mühendisliği (over-engineering) tespit eder.",
            "prompt_template",
            "[ARAÇ: ponytail-review] Son yazdığın kodları incele; gereksiz soyutlamaları, tekrarları ve karmaşık blokları en sade ve temiz standart kütüphane yöntemleriyle sadeleştir.",
            "✂️",
            1,
        ),
        (
            "skill-code-review",
            "Derin Kod İncelemesi (5 Eksen)",
            "quality",
            "Doğruluk, okunabilirlik, mimari, güvenlik ve performans eksenlerinde kod incelemesi başlatır.",
            "prompt_template",
            "[ARAÇ: code-review-and-quality] Çalışma alanındaki son değişiklikleri Doğruluk, Mimari, Güvenlik ve Performans açısından incele, varsa hataları düzelt.",
            "🔍",
            1,
        ),
        (
            "memory-sync",
            "TEAM_MEMORY.md Senkronizasyonu",
            "orchestration",
            "Ajanın tamamladığı görevleri ortak proje hafızasına (TEAM_MEMORY.md) işlemesini sağlar.",
            "prompt_template",
            "Tamamladığın son görevleri ve mimari durumu TEAM_MEMORY.md dosyasındaki kendi satırına ve ilgili history/ raporuna kaydet.",
            "🧠",
            1,
        ),
    ]
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for tid, name, cat, desc, ttype, cmd, icon, is_b in builtin_tools:
        conn.execute(
            """
            INSERT INTO tools_registry (id, name, category, description, tool_type, command_or_prompt, icon, is_builtin, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name=excluded.name,
                category=excluded.category,
                description=excluded.description,
                tool_type=excluded.tool_type,
                command_or_prompt=excluded.command_or_prompt,
                icon=excluded.icon
            """,
            (tid, name, cat, desc, ttype, cmd, icon, is_b, now),
        )


def parse_env_file(cfg_file: Path) -> Dict[str, str]:
    if not cfg_file.exists():
        return {}
    data: Dict[str, str] = {}
    for line in cfg_file.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            data[k.strip()] = v.strip().strip('"').strip("'")
    return data


def sync_and_migrate() -> None:
    """Migrates existing teams into SQLite state.db portably."""
    init_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with get_db() as conn:
        if TEAMS_DIR.exists():
            for d in sorted(TEAMS_DIR.iterdir()):
                if not d.is_dir():
                    continue
                cfg_file = d / "config.env"
                if not cfg_file.exists():
                    continue
                cfg = parse_env_file(cfg_file)
                tname = d.name
                pdir = cfg.get("PROJECT_DIR", str(default_projects_root() / tname))
                sess = cfg.get("SESSION_NAME", f"agy-{tname}")
                lrole = cfg.get("LEAD_ROLE", "Tech Lead & Supervision")
                lcid = cfg.get("LEAD_CONVERSATION_ID", "")
                cat = cfg.get("CREATED_AT", now)

                # Dynamically check active lead conversation for Anikuro
                if tname == "anikuro" and (BRAIN_DIR / "50b515c0-93a1-4fb7-acac-56162525fd73").exists():
                    lcid = "50b515c0-93a1-4fb7-acac-56162525fd73"

                conn.execute(
                    """
                    INSERT INTO teams (name, project_dir, session_name, lead_role, lead_cid, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(name) DO UPDATE SET
                        project_dir=excluded.project_dir,
                        lead_role=excluded.lead_role,
                        lead_cid=CASE WHEN teams.lead_cid = '' THEN excluded.lead_cid ELSE teams.lead_cid END
                    """,
                    (tname, pdir, sess, lrole, lcid, cat),
                )

                existing_count = conn.execute(
                    "SELECT COUNT(*) FROM agents WHERE team_name = ?", (tname,)
                ).fetchone()[0]

                if existing_count == 0:
                    afile = d / "agents.json"
                    saved = []
                    if afile.exists():
                        try:
                            saved = json.loads(afile.read_text(encoding="utf-8"))
                        except Exception:
                            saved = []
                    if not saved:
                        saved = [
                            {"id": 1, "name": "Agent 1", "role": "Worker #1", "target": "@1", "cid": "", "pane": 0, "runtime": "agy"},
                            {"id": 2, "name": "Agent 2", "role": "Worker #2", "target": "@2", "cid": "", "pane": 1, "runtime": "agy"},
                            {"id": 3, "name": "Agent 3", "role": "Worker #3", "target": "@3", "cid": "", "pane": 2, "runtime": "agy"},
                            {"id": 4, "name": "Agent 4", "role": "Worker #4", "target": "@4", "cid": "", "pane": 3, "runtime": "agy"},
                        ]
                    for idx, ag in enumerate(saved):
                        aid = ag.get("id", idx + 1)
                        target = ag.get("target", f"@{aid}")
                        if not target.startswith("@"):
                            target = f"@{target}"
                        conn.execute(
                            """
                            INSERT OR IGNORE INTO agents
                            (team_name, aid, name, role, target, runtime, model, cid, workspace_dir, skills_json, tools_json, pane, created_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                tname,
                                aid,
                                ag.get("name", f"Agent {aid}"),
                                ag.get("role", f"Worker #{aid}"),
                                target,
                                ag.get("runtime", "agy"),
                                ag.get("model", ""),
                                ag.get("cid", ""),
                                ag.get("workspace_dir", pdir),
                                json.dumps(ag.get("skills", [])),
                                json.dumps(ag.get("tools", ["git-status-diff"])),
                                ag.get("pane", idx),
                                now,
                            ),
                        )
                export_agents_json(conn, tname)


def export_agents_json(conn: sqlite3.Connection, team_name: str) -> None:
    """Keeps ~/.agy-teams/teams/<team>/agents.json synchronized with SQLite."""
    rows = conn.execute(
        "SELECT * FROM agents WHERE team_name = ? ORDER BY aid ASC", (team_name,)
    ).fetchall()
    payload = []
    for idx, r in enumerate(rows):
        payload.append({
            "id": r["aid"],
            "name": r["name"],
            "role": r["role"],
            "target": r["target"],
            "runtime": r["runtime"] if "runtime" in r.keys() else "agy",
            "model": r["model"] if "model" in r.keys() else "",
            "cid": r["cid"] or "",
            "persona": r["persona"] or "",
            "effort": r["effort"] or "medium",
            "mode": r["mode"] or "auto",
            "workspace_dir": r["workspace_dir"] or "",
            "skills": json.loads(r["skills_json"] or "[]"),
            "tools": json.loads(r["tools_json"] or "[]"),
            "pane": idx,
        })
    tdir = TEAMS_DIR / team_name
    tdir.mkdir(parents=True, exist_ok=True)
    (tdir / "agents.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )


# ----------------- Dual Snapshot Reader: Brain JSONL + SQLite Turns -----------------

def read_tail_jsonl(file_path: Path, max_bytes: int = 650_000, max_steps: int = 140) -> List[Dict[str, Any]]:
    if not file_path.exists():
        return []
    try:
        size = file_path.stat().st_size
        if size == 0:
            return []
        with open(file_path, "rb") as f:
            if size > max_bytes:
                f.seek(size - max_bytes)
                raw = f.read().decode("utf-8", errors="ignore")
                lines = raw.splitlines()[1:]
            else:
                raw = f.read().decode("utf-8", errors="ignore")
                lines = raw.splitlines()

        steps: List[Dict[str, Any]] = []
        for line in lines[-max_steps:]:
            line = line.strip()
            if not line:
                continue
            try:
                steps.append(json.loads(line))
            except Exception:
                continue
        return steps
    except Exception:
        return []


def clean_user_prompt(raw: str) -> str:
    if not raw:
        return ""
    m = re.search(r"<USER_REQUEST>\s*(.*?)\s*</USER_REQUEST>", raw, flags=re.DOTALL)
    if m:
        return m.group(1).strip()
    return raw.strip()


def summarize_tool_call(tc: Dict[str, Any]) -> Dict[str, str]:
    name = tc.get("name", "tool")
    args = tc.get("args", {}) or {}
    detail = ""
    if isinstance(args, dict):
        for k in ("Path", "AbsolutePath", "TargetFile", "CommandLine", "Query", "Pattern", "SearchPath", "toolSummary", "toolAction"):
            if k in args and args[k]:
                val = str(args[k]).strip('"')
                if k in ("Path", "AbsolutePath", "TargetFile"):
                    val = Path(val).name
                detail = val[:48]
                break
    return {"name": name, "detail": detail}


def get_runtime_context_limit(runtime: str = "agy", model: str = "") -> int:
    """Returns the model context window limit in tokens based on runtime/model."""
    m = (model or "").lower()
    r = (runtime or "agy").lower().strip()
    if "claude" in m or r == "claude":
        return 200_000
    if "codex" in m or "gpt-4" in m or "o1" in m or "o3" in m or r == "codex":
        return 128_000
    if "gemini" in m or r == "agy":
        return 1_000_000
    if "llama" in m or "qwen" in m:
        return 131_072
    if "deepseek" in m:
        return 64_000
    if r == "ollama":
        return 32_768
    return 128_000


def read_brain_snapshot(
    cid: str,
    task_key: str = "",
    runtime: str = "agy",
    team_name: str = "",
    target: str = "",
    model: str = "",
) -> Dict[str, Any]:
    """
    Unified reader:
    - If runtime == 'agy': reads directly from ~/.gemini/antigravity-cli/brain/<cid>/transcript_full.jsonl
    - If runtime != 'agy': reads recent agent_turns from SQLite
    Extracts live context tokens, model context limit, remaining capacity, and cumulative expenditure.
    """
    is_subproc_running = task_key in ACTIVE_PROCESSES and ACTIVE_PROCESSES[task_key].returncode is None
    if task_key and ":" in task_key:
        parts = task_key.split(":", 1)
        if not team_name:
            team_name = parts[0]
        if not target:
            target = parts[1]

    context_limit = get_runtime_context_limit(runtime, model)

    # NON-AGY RUNTIMES (Claude, Codex, Aider, Ollama, Custom)
    if runtime != "agy":
        with get_db() as conn:
            rows = conn.execute(
                """
                SELECT * FROM agent_turns
                WHERE team_name = ? AND target = ?
                ORDER BY id DESC LIMIT 50
                """,
                (team_name, target),
            ).fetchall()

        if not rows:
            return {
                "status": "working" if is_subproc_running else "idle",
                "markdown": f"*[{runtime.upper()} Ajanı Hazır]*\n\nKomut göndermek için aşağıdaki çubuğu kullanabilirsiniz.",
                "terminal": f"Runtime: {runtime}\nWaiting for turn execution...",
                "thinking": "",
                "tool_calls": [],
                "telemetry": {
                    "steps": 0,
                    "input_tokens": 0,
                    "cache_tokens": 0,
                    "output_tokens": 0,
                    "context_tokens": 0,
                    "context_limit": context_limit,
                    "remaining_tokens": context_limit,
                    "context_pct": 0.0,
                    "cum_input_tokens": 0,
                    "cum_cache_tokens": 0,
                    "cum_output_tokens": 0,
                    "cum_total_tokens": 0,
                },
            }

        md_sections = []
        term_logs = []
        latest_thinking = ""
        recent_tools = []
        cum_in = 0
        cum_out = 0

        for r in reversed(rows[:5]):
            md_sections.append(f"> **🎯 Görev:** {r['user_prompt'][:160]}\n\n{r['response_md']}")
            if r["thinking"]:
                latest_thinking = r["thinking"]
            if r["command_logs"]:
                term_logs.append(r["command_logs"])
            if r["tool_calls_json"]:
                try:
                    recent_tools.extend(json.loads(r["tool_calls_json"]))
                except Exception:
                    pass

        for r in rows:
            in_t = r["input_tokens"] if ("input_tokens" in r.keys() and r["input_tokens"]) else max(1, len(r["user_prompt"]) // 4)
            out_t = r["output_tokens"] if ("output_tokens" in r.keys() and r["output_tokens"]) else max(1, len(r["response_md"]) // 4)
            cum_in += in_t
            cum_out += out_t

        last_r = rows[0] if rows else None
        last_in = (last_r["input_tokens"] if ("input_tokens" in last_r.keys() and last_r["input_tokens"]) else max(1, len(last_r["user_prompt"]) // 4)) if last_r else 0
        last_out = (last_r["output_tokens"] if ("output_tokens" in last_r.keys() and last_r["output_tokens"]) else max(1, len(last_r["response_md"]) // 4)) if last_r else 0
        context_tokens = last_in + last_out
        remaining_tokens = max(0, context_limit - context_tokens)
        context_pct = round((context_tokens / context_limit) * 100, 1) if context_limit > 0 else 0.0

        return {
            "status": "working" if is_subproc_running else "idle",
            "markdown": "\n\n---\n\n".join(md_sections[-3:]),
            "terminal": "\n\n".join(term_logs[-4:]) if term_logs else f"Runtime: {runtime}",
            "thinking": latest_thinking[-1200:] if latest_thinking else "",
            "tool_calls": recent_tools[-6:],
            "telemetry": {
                "steps": len(rows),
                "input_tokens": last_in,
                "cache_tokens": 0,
                "output_tokens": last_out,
                "context_tokens": context_tokens,
                "context_limit": context_limit,
                "remaining_tokens": remaining_tokens,
                "context_pct": context_pct,
                "cum_input_tokens": cum_in,
                "cum_cache_tokens": 0,
                "cum_output_tokens": cum_out,
                "cum_total_tokens": cum_in + cum_out,
            },
        }

    # AGY RUNTIME
    if not cid:
        status = "working" if is_subproc_running else "idle"
        msg = "⚡ *Görev yürütülüyor, konuşma kimliği (CID) oluşturuluyor...*" if is_subproc_running else "*Henüz görev atanmadı. Komut göndermek için aşağıdaki çubuğu veya **Araçlar** menüsünü kullanın.*"
        return {
            "status": status,
            "markdown": msg,
            "terminal": "Waiting for task execution...",
            "thinking": "",
            "tool_calls": [],
            "telemetry": {
                "steps": 0,
                "input_tokens": 0,
                "cache_tokens": 0,
                "output_tokens": 0,
                "context_tokens": 0,
                "context_limit": context_limit,
                "remaining_tokens": context_limit,
                "context_pct": 0.0,
                "cum_input_tokens": 0,
                "cum_cache_tokens": 0,
                "cum_output_tokens": 0,
                "cum_total_tokens": 0,
            },
        }

    log_dir = BRAIN_DIR / cid / ".system_generated" / "logs"
    full_file = log_dir / "transcript_full.jsonl"
    compact_file = log_dir / "transcript.jsonl"
    target_file = full_file if full_file.exists() else compact_file
    token_file = compact_file if compact_file.exists() else target_file

    # Fast cumulative token sweep from compact transcript
    cum_in = 0
    cum_cache = 0
    cum_out = 0
    if token_file and token_file.exists():
        try:
            with open(token_file, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if '"input_tokens"' in line:
                        try:
                            d = json.loads(line)
                            cum_in += d.get("input_tokens", 0)
                            cum_cache += d.get("cache_read_tokens", 0)
                            cum_out += d.get("output_tokens", 0)
                        except Exception:
                            pass
        except Exception:
            pass

    steps = read_tail_jsonl(target_file, max_bytes=650_000, max_steps=140)
    if not steps:
        return {
            "status": "working" if is_subproc_running else "idle",
            "markdown": f"*Konuşma (`{cid[:8]}`) hazır, çıktı bekleniyor...*",
            "terminal": f"Brain CID: {cid}\nNo steps recorded yet.",
            "thinking": "",
            "tool_calls": [],
            "telemetry": {
                "steps": 0,
                "input_tokens": 0,
                "cache_tokens": 0,
                "output_tokens": 0,
                "context_tokens": 0,
                "context_limit": context_limit,
                "remaining_tokens": context_limit,
                "context_pct": 0.0,
                "cum_input_tokens": cum_in,
                "cum_cache_tokens": cum_cache,
                "cum_output_tokens": cum_out,
                "cum_total_tokens": cum_in + cum_cache + cum_out,
            },
        }

    last_step = steps[-1]
    last_status = str(last_step.get("status", "DONE")).upper()
    last_type = str(last_step.get("type", ""))

    turn_completed = (
        last_type == "PLANNER_RESPONSE"
        and last_status == "DONE"
        and bool(str(last_step.get("content", "")).strip())
        and not bool(last_step.get("tool_calls"))
    )

    status = "idle"
    if is_subproc_running or last_status == "RUNNING":
        status = "working"
    elif last_status == "ERROR":
        status = "error"
    elif not turn_completed:
        try:
            mtime = target_file.stat().st_mtime
            if (time.time() - mtime) < 180:
                status = "working"
        except Exception:
            pass

    md_sections: List[str] = []
    term_logs: List[str] = []
    latest_thinking = ""
    recent_tools: List[Dict[str, str]] = []
    telemetry = {
        "steps": last_step.get("step_index", len(steps)),
        "input_tokens": 0,
        "cache_tokens": 0,
        "output_tokens": 0,
    }

    for s in steps:
        stype = s.get("type", "")
        if s.get("input_tokens"):
            telemetry["input_tokens"] = s.get("input_tokens", 0)
            telemetry["cache_tokens"] = s.get("cache_read_tokens", 0)
            telemetry["output_tokens"] = s.get("output_tokens", 0)

        if stype == "USER_INPUT":
            prompt_txt = clean_user_prompt(s.get("content", ""))
            if prompt_txt:
                first_line = prompt_txt.splitlines()[0][:160]
                md_sections.append(f"> **🎯 Görev:** {first_line}")
        elif stype == "PLANNER_RESPONSE":
            if s.get("thinking"):
                latest_thinking = str(s["thinking"]).strip()
            tcalls = s.get("tool_calls") or []
            for tc in tcalls:
                recent_tools.append(summarize_tool_call(tc))
            content = str(s.get("content", "")).strip()
            if content:
                md_sections.append(content)
        elif stype == "GENERIC":
            gcontent = str(s.get("content", "")).strip()
            if gcontent:
                term_logs.append(f"--- [Step #{s.get('step_index', '?')} • {s.get('status', 'DONE')}] ---\n{gcontent[-1200:]}")

    if status == "working" and not turn_completed:
        active_tools_str = ", ".join(f"`{t['name']}({t['detail']})`" if t['detail'] else f"`{t['name']}`" for t in recent_tools[-4:])
        live_banner = f"### ⚡ Ajan Aktif Çalışıyor (Adım #{telemetry['steps']})\n"
        if latest_thinking:
            live_banner += f"- **Son Düşünce:** *{latest_thinking[:280]}*\n"
        if active_tools_str:
            live_banner += f"- **Son Araç Çağrıları:** {active_tools_str}"
        md_sections.append(live_banner)

    display_md = "\n\n---\n\n".join(md_sections[-4:]) if md_sections else "*Ajan araç çalıştırıyor...*"
    display_term = "\n\n".join(term_logs[-6:]) if term_logs else "Henüz terminal / araç çıktısı yok."

    last_in = telemetry.get("input_tokens", 0)
    last_cache = telemetry.get("cache_tokens", 0)
    last_out = telemetry.get("output_tokens", 0)
    context_tokens = last_in + last_cache + last_out
    remaining_tokens = max(0, context_limit - context_tokens)
    context_pct = round((context_tokens / context_limit) * 100, 1) if context_limit > 0 else 0.0

    cum_total = cum_in + cum_cache + cum_out
    if cum_total == 0 and context_tokens > 0:
        cum_in, cum_cache, cum_out, cum_total = last_in, last_cache, last_out, context_tokens

    telemetry["context_tokens"] = context_tokens
    telemetry["context_limit"] = context_limit
    telemetry["remaining_tokens"] = remaining_tokens
    telemetry["context_pct"] = context_pct
    telemetry["cum_input_tokens"] = cum_in
    telemetry["cum_cache_tokens"] = cum_cache
    telemetry["cum_output_tokens"] = cum_out
    telemetry["cum_total_tokens"] = cum_total

    return {
        "status": status,
        "markdown": display_md,
        "terminal": display_term,
        "thinking": latest_thinking[-1200:] if latest_thinking else "",
        "tool_calls": recent_tools[-6:],
        "telemetry": telemetry,
    }


# ----------------- Multi-CLI Process Execution Adapter -----------------

def find_interactive_tmux_pane(cid: str = "", target: str = "") -> Optional[str]:
    """Finds exact immutable pane_id in tmux by matching PID or target title."""
    if IS_WINDOWS or not shutil.which("tmux"):
        return None
    try:
        res = subprocess.run(
            ["tmux", "list-panes", "-a", "-F", "#{pane_id}|#{pane_pid}|#{pane_title}"],
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode != 0 or not res.stdout.strip():
            return None

        # Check by pane title matching target (e.g. "@server")
        if target:
            target_clean = target.lower().strip()
            for line in res.stdout.strip().splitlines():
                parts = line.split("|")
                if len(parts) >= 3 and target_clean in parts[2].lower():
                    return parts[0].strip()

        # Check by CID matching agy process
        if cid:
            ps_res = subprocess.run(["ps", "-eo", "pid,ppid,args"], capture_output=True, text=True, check=False)
            pane_by_pid = {line.split("|")[1].strip(): line.split("|")[0].strip() for line in res.stdout.strip().splitlines() if "|" in line}
            for line in ps_res.stdout.splitlines():
                if cid in line and "agy" in line:
                    tokens = line.strip().split(None, 2)
                    if len(tokens) >= 2:
                        pid, ppid = tokens[0], tokens[1]
                        if ppid in pane_by_pid:
                            return pane_by_pid[ppid]
                        if pid in pane_by_pid:
                            return pane_by_pid[pid]
    except Exception:
        pass
    return None


def sync_team_orchestration_doc(team_name: str, project_dir: str = ""):
    """Generates and syncs TEAM_ORCHESTRATION.md in the project directory so all agents know the team, roles, and rules."""
    pdir = None
    if project_dir and Path(project_dir).exists():
        pdir = Path(project_dir)
    else:
        with get_db() as conn:
            t = conn.execute("SELECT project_dir FROM teams WHERE name = ?", (team_name,)).fetchone()
            if t and t["project_dir"] and Path(t["project_dir"]).exists():
                pdir = Path(t["project_dir"])
    if not pdir:
        return

    with get_db() as conn:
        team = conn.execute("SELECT * FROM teams WHERE name = ?", (team_name,)).fetchone()
        if not team:
            return
        agents = conn.execute("SELECT * FROM agents WHERE team_name = ? ORDER BY aid ASC", (team_name,)).fetchall()

    doc_lines = [
        f"# 🐝 HiveForge Takım Orkestrasyonu: {team_name.upper()}",
        f"> Bu proje **HiveForge** otonom çoklu ajan (Multi-Agent) sistemi tarafından yönetilmektedir.",
        "",
        "## 👥 Takım Yapısı ve Roller",
        f"- **Tech Lead (`@lead`)**: {team['lead_role']} [CLI: {(team['lead_runtime'] or 'agy').upper()}]",
    ]
    for ag in agents:
        r_type = ag["runtime"] or "agy"
        doc_lines.append(f"- **{ag['name']} (`{ag['target']}`)**: {ag['role']} [CLI: {r_type.upper()}]")

    doc_lines.extend([
        "",
        "## 📡 Ajanlar Arası İletişim Kuralları",
        "1. **Asenkron İletişim (`/btw`)**: Başka bir ajana veya tüm takıma bilgi, durum ya da istek iletmek için `/btw @hedef [mesaj]` formatını kullanın. HiveForge sistemi bu mesajları otomatik olarak ilgili ajanın bağlamına aktarır.",
        "2. **Çakışma ve Dosya Kilitleri**: Ortak repoda başka bir ajanın değiştirdiği dosyaları ezmemek için `.locks/locks.json` dosyasını kontrol edin.",
        "3. **Terminal ve Araçlar**: Terminal üzerinden `hive agents` veya `team agents` ile anlık takım durumunu görebilirsiniz.",
        "",
        f"*Otomatik oluşturuldu: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*",
    ])

    try:
        (pdir / "TEAM_ORCHESTRATION.md").write_text("\n".join(doc_lines), encoding="utf-8")
        (pdir / "AGENTS.md").write_text("\n".join(doc_lines), encoding="utf-8")
    except Exception:
        pass


def get_team_token_analytics(team_name: str) -> Dict[str, Any]:
    """
    Computes comprehensive token analytics for the entire team:
    - Total tokens spent (cumulative)
    - Total active context tokens & remaining capacity
    - Per-agent breakdown with share percentage and visual gauge metrics
    - Top token consumer identification
    """
    sync_and_migrate()
    with get_db() as conn:
        team = conn.execute("SELECT * FROM teams WHERE name = ?", (team_name,)).fetchone()
        if not team:
            return {"success": False, "error": f"Takım bulunamadı: {team_name}"}
        lead_cid = team["lead_cid"] or ""
        lead_runtime = team["lead_runtime"] if ("lead_runtime" in team.keys() and team["lead_runtime"]) else "agy"
        agents_rows = conn.execute("SELECT * FROM agents WHERE team_name = ? ORDER BY aid ASC", (team_name,)).fetchall()

    members = []

    # 1. Tech Lead
    lead_snap = read_brain_snapshot(lead_cid, task_key=f"{team_name}:@lead", runtime=lead_runtime)
    lead_tel = lead_snap.get("telemetry", {})
    members.append({
        "target": "@lead",
        "name": f"{team_name.title()} Tech Lead",
        "role": team["lead_role"],
        "runtime": lead_runtime,
        "model": "",
        "is_lead": True,
        "cid": lead_cid[:8] if lead_cid else "lead",
        "full_cid": lead_cid,
        "telemetry": lead_tel,
    })

    # 2. Worker Agents
    for r in agents_rows:
        cid = r["cid"] or ""
        r_runtime = r["runtime"] if ("runtime" in r.keys() and r["runtime"]) else "agy"
        r_model = r["model"] if ("model" in r.keys() and r["model"]) else ""
        snap = read_brain_snapshot(cid, task_key=f"{team_name}:{r['target']}", runtime=r_runtime, model=r_model)
        tel = snap.get("telemetry", {})
        members.append({
            "target": r["target"],
            "name": r["name"],
            "role": r["role"],
            "runtime": r_runtime,
            "model": r_model,
            "is_lead": False,
            "cid": cid[:8] if cid else "new",
            "full_cid": cid,
            "telemetry": tel,
        })

    # Aggregations
    total_cum_tokens = sum(m["telemetry"].get("cum_total_tokens", 0) for m in members)
    total_context_tokens = sum(m["telemetry"].get("context_tokens", 0) for m in members)
    total_context_limit = sum(m["telemetry"].get("context_limit", 1_000_000) for m in members)
    total_remaining_tokens = max(0, total_context_limit - total_context_tokens)
    total_context_pct = round((total_context_tokens / total_context_limit) * 100, 1) if total_context_limit > 0 else 0.0
    total_input_tokens = sum(m["telemetry"].get("cum_input_tokens", 0) for m in members)
    total_cache_tokens = sum(m["telemetry"].get("cum_cache_tokens", 0) for m in members)
    total_output_tokens = sum(m["telemetry"].get("cum_output_tokens", 0) for m in members)

    # Fallback if cumulative sum is 0 but context has values
    if total_cum_tokens == 0 and total_context_tokens > 0:
        total_cum_tokens = total_context_tokens

    # Compute individual shares and sort
    for m in members:
        tel = m["telemetry"]
        m_cum = tel.get("cum_total_tokens", 0)
        if m_cum == 0 and tel.get("context_tokens", 0) > 0:
            m_cum = tel.get("context_tokens", 0)
        m["cum_tokens"] = m_cum
        m["cum_total_tokens"] = m_cum
        m["cum_input_tokens"] = tel.get("cum_input_tokens", 0)
        m["cum_cache_tokens"] = tel.get("cum_cache_tokens", 0)
        m["cum_output_tokens"] = tel.get("cum_output_tokens", 0)
        m["context_tokens"] = tel.get("context_tokens", 0)
        m["context_limit"] = tel.get("context_limit", 1_000_000)
        m["remaining_tokens"] = tel.get("remaining_tokens", m["context_limit"])
        m["context_pct"] = tel.get("context_pct", 0.0)
        m["share_pct"] = round((m_cum / total_cum_tokens) * 100, 1) if total_cum_tokens > 0 else 0.0
        m["pct_of_team_tokens"] = m["share_pct"]
        m["steps"] = tel.get("steps", 0)

    sorted_members = sorted(members, key=lambda x: (x["cum_tokens"], x["context_tokens"]), reverse=True)
    top_consumer = None
    if sorted_members and sorted_members[0]["cum_tokens"] > 0:
        top = sorted_members[0]
        top_consumer = {
            "target": top["target"],
            "name": top["name"],
            "runtime": top["runtime"],
            "tokens": top["cum_tokens"],
            "cum_total_tokens": top["cum_tokens"],
            "share_pct": top["share_pct"],
            "pct_of_team_tokens": top["share_pct"],
        }

    cache_hit_pct = 0.0
    if (total_input_tokens + total_cache_tokens) > 0:
        cache_hit_pct = round((total_cache_tokens / (total_input_tokens + total_cache_tokens)) * 100, 1)

    return {
        "success": True,
        "team": team_name,
        "total_tokens": total_cum_tokens,
        "total_cum_tokens": total_cum_tokens,
        "total_context_tokens": total_context_tokens,
        "total_context_limit": total_context_limit,
        "total_remaining_tokens": total_remaining_tokens,
        "total_context_pct": total_context_pct,
        "total_input_tokens": total_input_tokens,
        "total_cache_tokens": total_cache_tokens,
        "total_output_tokens": total_output_tokens,
        "cache_hit_pct": cache_hit_pct,
        "top_consumer": top_consumer,
        "agents": sorted_members,
    }


def build_agent_orchestration_prompt(team_name: str, target: str, user_prompt: str) -> str:
    """Injects orchestration context so every agent knows its identity, teammates, and /btw protocol."""
    try:
        with get_db() as conn:
            team = conn.execute("SELECT * FROM teams WHERE name = ?", (team_name,)).fetchone()
            if not team:
                return user_prompt
            agents = conn.execute("SELECT target, name, role, runtime FROM agents WHERE team_name = ? ORDER BY aid ASC", (team_name,)).fetchall()

        teammates = []
        if target != "@lead":
            teammates.append(f"@lead (Tech Lead: {team['lead_role']})")
        for ag in agents:
            if ag["target"] != target:
                teammates.append(f"{ag['target']} ({ag['name']}: {ag['role']})")

        teammates_str = ", ".join(teammates) if teammates else "Yok (Tekil Çalışma)"

        ctx_prefix = (
            f"[HIVEFORGE AGENT ORKESTRASYON BAĞLAMI]\n"
            f"• Takım: {team_name} | Senin Rolün: {target} | Takım Arkadaşların: {teammates_str}\n"
            f"• İletişim: Diğer ajanlara bilgi iletmek için cevabında veya notlarında `/btw @hedef [mesaj]` formatını kullan.\n"
            f"• Dosya Kilitleri: Çakışmaları engellemek için ortak depodaki dosya kilitlerine (.locks/) dikkat et.\n"
            f"--------------------------------------------------\n"
        )
        return ctx_prefix + user_prompt
    except Exception:
        return user_prompt


async def execute_headless_agent_turn(
    team_name: str,
    target: str,
    runtime: str,
    model: str,
    cid: str,
    workspace_dir: str,
    persona: str,
    effort: str,
    mode: str,
    prompt: str,
    is_lead: bool = False,
) -> Tuple[bool, str, str]:
    """
    Multi-CLI Subprocess Runner:
    - 'agy': agy --mode auto -p ...
    - 'claude': claude --dangerously-skip-permissions -p ...
    - 'codex': codex exec / run ...
    - 'aider': aider --message ... --yes-always
    - 'ollama': ollama run <model> ...
    - 'custom': custom CLI execution
    """
    task_key = f"{team_name}:{target}"
    wdir = workspace_dir if (workspace_dir and Path(workspace_dir).exists()) else str(Path.home())
    runtime = (runtime or "agy").lower().strip()

    # Sync orchestration documents & inject team awareness into prompt
    sync_team_orchestration_doc(team_name, wdir)
    effective_prompt = build_agent_orchestration_prompt(team_name, target, prompt)

    cmd: List[str] = []
    before_cids = set()

    if runtime == "agy":
        if not cid and BRAIN_DIR.exists():
            before_cids = {p.name for p in BRAIN_DIR.iterdir() if p.is_dir()}
        cmd = ["agy", "--mode", mode or "auto"]
        if effort in ("low", "medium", "high", "xhigh", "max"):
            cmd.extend(["--effort", effort])
        if persona:
            cmd.extend(["--agent", persona])
        if cid:
            cmd.extend(["--conversation", cid])
        cmd.extend(["-p", effective_prompt])

    elif runtime == "claude":
        cmd = ["claude", "--dangerously-skip-permissions"]
        if effort in ("low", "medium", "high"):
            cmd.extend(["--effort", effort])
        cmd.extend(["-p", effective_prompt])

    elif runtime == "codex":
        # OpenAI Codex CLI runner
        target_model = model or "gpt-4o"
        cmd = ["codex"]
        if model:
            cmd.extend(["-m", target_model])
        cmd.extend(["exec", effective_prompt] if shutil.which("codex") else ["run", effective_prompt])

    elif runtime == "aider":
        cmd = ["aider", "--message", effective_prompt, "--yes-always", "--no-git"]
        if model:
            cmd.extend(["--model", model])

    elif runtime == "ollama":
        target_model = model or "llama3.2"
        cmd = ["ollama", "run", target_model, effective_prompt]

    else:
        # Custom runtime command template
        cmd = ["bash", "-c", f"{runtime} '{effective_prompt}'"]
        if IS_WINDOWS:
            git_bash = _windows_git_bash()
            if git_bash:
                cmd[0] = git_bash
            else:
                safe_prompt = _flatten_for_cmd(effective_prompt).replace('"', "'")
                cmd = [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/s", "/c", f'{runtime} "{safe_prompt}"']

    # Check CLI tool availability
    bin_name = cmd[0]
    if not shutil.which(bin_name):
        return False, cid, f"Hata: '{bin_name}' CLI komutu bu sistemde kurulu değil."

    proc = await asyncio.create_subprocess_exec(
        *resolve_cli_command(cmd),
        cwd=wdir,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    ACTIVE_PROCESSES[task_key] = proc
    ACTIVE_TASKS_META[task_key] = {
        "started_at": time.time(),
        "prompt": prompt[:120],
        "pid": proc.pid,
        "runtime": runtime,
    }

    # For agy: auto-detect new CID if empty
    detected_cid = cid
    if runtime == "agy" and not detected_cid:
        for _ in range(25):
            await asyncio.sleep(0.4)
            if BRAIN_DIR.exists():
                current_cids = {p.name for p in BRAIN_DIR.iterdir() if p.is_dir()}
                diff = current_cids - before_cids
                if diff:
                    newest = max(diff, key=lambda name: (BRAIN_DIR / name).stat().st_mtime)
                    detected_cid = newest
                    with get_db() as conn:
                        if is_lead:
                            conn.execute("UPDATE teams SET lead_cid = ? WHERE name = ?", (detected_cid, team_name))
                        else:
                            conn.execute("UPDATE agents SET cid = ? WHERE team_name = ? AND target = ?", (detected_cid, team_name, target))
                            export_agents_json(conn, team_name)
                    break
            if proc.returncode is not None:
                break

    try:
        stdout_b, stderr_b = await proc.communicate()
        stdout = stdout_b.decode("utf-8", errors="ignore").strip()
        stderr = stderr_b.decode("utf-8", errors="ignore").strip()
        ok = proc.returncode == 0
        output_txt = stdout or stderr

        # For non-agy runtimes: store turn in SQLite agent_turns table
        if runtime != "agy":
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            est_in = max(1, len(prompt) // 4)
            est_out = max(1, len(stdout) // 4)
            with get_db() as conn:
                conn.execute(
                    """
                    INSERT INTO agent_turns
                    (team_name, target, runtime, user_prompt, response_md, command_logs, status, created_at, input_tokens, output_tokens, total_tokens)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (team_name, target, runtime, prompt, stdout or "*Çıktı üretilmedi*", stderr, "DONE" if ok else "ERROR", now, est_in, est_out, est_in + est_out),
                )
    finally:
        ACTIVE_PROCESSES.pop(task_key, None)
        ACTIVE_TASKS_META.pop(task_key, None)

    return ok, detected_cid, output_txt


async def dispatch_message(
    team_name: str,
    target: str,
    message: str,
    sender: str = "User",
    msg_type: str = "dispatch",
    tool_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Central dispatcher supporting agy, claude, aider, ollama, and custom runtimes."""
    sync_and_migrate()
    with get_db() as conn:
        team = conn.execute("SELECT * FROM teams WHERE name = ?", (team_name,)).fetchone()
        if not team:
            return {"success": False, "error": f"Takım bulunamadı: {team_name}"}

        enriched_message = message
        if tool_id:
            tool = conn.execute("SELECT * FROM tools_registry WHERE id = ?", (tool_id,)).fetchone()
            if tool:
                if tool["tool_type"] == "shell_context":
                    wdir = team["project_dir"]
                    if target not in ("@all", "all", "@lead", "lead"):
                        ag_row = conn.execute(
                            "SELECT workspace_dir FROM agents WHERE team_name = ? AND target = ?",
                            (team_name, target),
                        ).fetchone()
                        if ag_row and ag_row["workspace_dir"]:
                            wdir = ag_row["workspace_dir"]
                    try:
                        proc = await create_shell_subprocess(
                            tool["command_or_prompt"],
                            cwd=wdir if Path(wdir).exists() else str(Path.home()),
                        )
                        out_b, err_b = await asyncio.wait_for(proc.communicate(), timeout=20.0)
                        tool_out = (out_b.decode("utf-8", errors="ignore") + "\n" + err_b.decode("utf-8", errors="ignore")).strip()
                    except Exception as e:
                        tool_out = f"Tool execution error: {e}"

                    if not message or message.strip() == "__TOOL_ONLY__":
                        return {
                            "success": True,
                            "tool_only": True,
                            "tool_name": tool["name"],
                            "output": tool_out[:4000],
                        }
                    enriched_message = (
                        f"[BAĞLI ARAÇ ÇIKTISI: {tool['name']}]\n```\n{tool_out[:2500]}\n```\n\n"
                        f"Yukarıdaki araç çıktısını dikkate alarak şu görevi uygula:\n{message}"
                    )
                elif tool["tool_type"] == "prompt_template":
                    enriched_message = f"{tool['command_or_prompt']}\n\n{message}".strip()

        targets_to_run: List[Dict[str, Any]] = []
        norm_target = target.strip().lower()
        if not norm_target.startswith("@") and norm_target not in ("all", "lead"):
            norm_target = f"@{norm_target}"

        if norm_target in ("@all", "all"):
            rows = conn.execute("SELECT * FROM agents WHERE team_name = ? ORDER BY aid ASC", (team_name,)).fetchall()
            for r in rows:
                targets_to_run.append(dict(r) | {"is_lead": False})
        elif norm_target in ("@lead", "lead"):
            targets_to_run.append({
                "target": "@lead",
                "name": f"{team_name.title()} Tech Lead",
                "role": team["lead_role"],
                "runtime": team["lead_runtime"] or "agy",
                "model": "",
                "cid": team["lead_cid"] or "",
                "persona": team["lead_persona"] or "",
                "effort": team["lead_effort"] or "high",
                "mode": "auto",
                "workspace_dir": team["project_dir"],
                "skills_json": "[]",
                "is_lead": True,
            })
        else:
            rows = conn.execute("SELECT * FROM agents WHERE team_name = ?", (team_name,)).fetchall()
            for r in rows:
                if (
                    r["target"].lower() == norm_target
                    or r["name"].lower() == target.strip().lower()
                    or str(r["aid"]) == target.strip().lstrip("@")
                ):
                    targets_to_run.append(dict(r) | {"is_lead": False})
                    break

        if not targets_to_run:
            return {"success": False, "error": f"Hedef ajan bulunamadı: {target}"}

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        dispatched_names = []

        for idx, ag in enumerate(targets_to_run):
            ag_target = ag["target"]
            ag_cid = ag.get("cid", "")
            ag_runtime = ag.get("runtime", "agy") or "agy"
            ag_model = ag.get("model", "") or ""
            ag_wdir = ag.get("workspace_dir") or team["project_dir"]
            skills = json.loads(ag.get("skills_json") or "[]")

            final_prompt = enriched_message
            if msg_type == "note":
                final_prompt = f"/btw [{sender}]: {enriched_message}"
            elif skills and not ag_cid and ag_runtime == "agy":
                skill_str = ", ".join(skills)
                final_prompt = (
                    f"[SİSTEM ROLÜ: {ag['name']} — {ag['role']} | Çalışma Dizini: {ag_wdir} | Aktif Yetenekler: {skill_str}]\n\n"
                    f"{enriched_message}"
                )

            conn.execute(
                """
                INSERT INTO dispatch_queue (team_name, target, sender, msg_type, message, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (team_name, ag_target, sender, msg_type, final_prompt, "running", now),
            )

            # Check if an interactive tmux pane is running
            interactive_pane = find_interactive_tmux_pane(cid=ag_cid, target=ag_target)
            if interactive_pane:
                subprocess.run(["tmux", "send-keys", "-t", interactive_pane, "-l", final_prompt], check=False)
                subprocess.run(["tmux", "send-keys", "-t", interactive_pane, "C-m"], check=False)
                dispatched_names.append(f"{ag['name']} ({ag_runtime.upper()} Canlı Tmux: {interactive_pane})")
            else:
                delay = idx * 0.6
                asyncio.create_task(
                    _delayed_headless_launch(
                        delay,
                        team_name,
                        ag_target,
                        ag_runtime,
                        ag_model,
                        ag_cid,
                        ag_wdir,
                        ag.get("persona", ""),
                        ag.get("effort", "medium"),
                        ag.get("mode", "auto"),
                        final_prompt,
                        bool(ag.get("is_lead")),
                    )
                )
                dispatched_names.append(f"{ag['name']} ({ag_runtime.upper()} Headless)")

        return {
            "success": True,
            "dispatched": dispatched_names,
            "output": f"Görev iletildi -> {', '.join(dispatched_names)}",
        }


async def _delayed_headless_launch(
    delay: float,
    team_name: str,
    target: str,
    runtime: str,
    model: str,
    cid: str,
    workspace_dir: str,
    persona: str,
    effort: str,
    mode: str,
    prompt: str,
    is_lead: bool,
) -> None:
    if delay > 0:
        await asyncio.sleep(delay)
    await execute_headless_agent_turn(
        team_name, target, runtime, model, cid, workspace_dir, persona, effort, mode, prompt, is_lead
    )


# ----------------- Ecosystem & Tool Discovery -----------------

_ECOSYSTEM_CACHE: Dict[str, Any] = {"ts": 0, "data": None}


def discover_agy_ecosystem() -> Dict[str, Any]:
    """Discovers installed CLI tools (agy, claude, aider, ollama), plugins, skills, and tools."""
    now = time.time()
    if _ECOSYSTEM_CACHE["data"] and (now - _ECOSYSTEM_CACHE["ts"] < 30):
        return _ECOSYSTEM_CACHE["data"]

    # Detect installed CLI coding agents on the host system
    available_runtimes = []
    for r in ["agy", "claude", "aider", "ollama"]:
        if shutil.which(r):
            available_runtimes.append(r)
    available_runtimes.append("custom")

    plugins = []
    skills = []
    personas = ["code-reviewer", "security-auditor", "test-engineer", "web-performance-auditor", "firestore-rules-author"]
    mcp_servers = []

    if shutil.which("agy"):
        try:
            res = subprocess.run(resolve_cli_command(["agy", "plugin", "list", "--json"]), capture_output=True, text=True, check=False, timeout=5)
            if res.returncode == 0 and res.stdout.strip():
                raw_plugins = json.loads(res.stdout)
                for p in raw_plugins:
                    p_skills = p.get("skills", []) or []
                    plugins.append({
                        "name": p.get("name"),
                        "version": p.get("version", ""),
                        "enabled": p.get("enabled", True),
                        "skills_count": len(p_skills),
                        "skills": p_skills,
                    })
                    for s in p_skills:
                        skills.append({"name": s, "plugin": p.get("name")})
        except Exception:
            pass

        try:
            res_m = subprocess.run(resolve_cli_command(["agy", "mcp", "list"]), capture_output=True, text=True, check=False, timeout=5)
            if res_m.returncode == 0 and res_m.stdout.strip():
                for line in res_m.stdout.strip().splitlines()[1:]:
                    parts = line.split(None, 3)
                    if len(parts) >= 3:
                        mcp_servers.append({
                            "name": parts[0],
                            "type": parts[1],
                            "status": parts[2],
                            "command": parts[3] if len(parts) > 3 else "",
                        })
        except Exception:
            pass

    with get_db() as conn:
        custom_tools = [dict(r) for r in conn.execute("SELECT * FROM tools_registry ORDER BY is_builtin DESC, name ASC").fetchall()]

    data = {
        "runtimes": available_runtimes,
        "plugins": plugins,
        "skills": skills,
        "personas": personas,
        "mcp_servers": mcp_servers,
        "tools": custom_tools,
    }
    _ECOSYSTEM_CACHE["ts"] = now
    _ECOSYSTEM_CACHE["data"] = data
    return data


if __name__ == "__main__":
    sync_and_migrate()
    print("[OK] AGY-VIBE Multi-CLI Engine initialized at:", DB_PATH)
