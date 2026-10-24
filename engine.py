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

# Portable environment-based directories
BASE_DIR = Path(os.environ.get("AGY_TEAMS_DIR", Path.home() / ".agy-teams"))
TEAMS_DIR = BASE_DIR / "teams"
DB_PATH = BASE_DIR / "state.db"
BRAIN_DIR = Path.home() / ".gemini" / "antigravity-cli" / "brain"
PROJECT_ROOT = Path(__file__).resolve().parent

BASE_DIR.mkdir(parents=True, exist_ok=True)
TEAMS_DIR.mkdir(parents=True, exist_ok=True)

# Active async subprocess tasks keyed by f"{team}:{target}"
ACTIVE_PROCESSES: Dict[str, asyncio.subprocess.Process] = {}
ACTIVE_TASKS_META: Dict[str, Dict[str, Any]] = {}


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
                pdir = cfg.get("PROJECT_DIR", str(Path.home() / "agy-teams" / tname))
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


def read_brain_snapshot(cid: str, task_key: str = "", runtime: str = "agy", team_name: str = "", target: str = "") -> Dict[str, Any]:
    """
    Unified reader:
    - If runtime == 'agy': reads directly from ~/.gemini/antigravity-cli/brain/<cid>/transcript_full.jsonl
    - If runtime != 'agy': reads recent agent_turns from SQLite
    """
    is_subproc_running = task_key in ACTIVE_PROCESSES and ACTIVE_PROCESSES[task_key].returncode is None

    # NON-AGY RUNTIMES (Claude, Aider, Ollama, Custom)
    if runtime != "agy":
        with get_db() as conn:
            rows = conn.execute(
                """
                SELECT * FROM agent_turns
                WHERE team_name = ? AND target = ?
                ORDER BY id DESC LIMIT 5
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
                "telemetry": {"steps": 0, "input_tokens": 0, "cache_tokens": 0, "output_tokens": 0},
            }

        md_sections = []
        term_logs = []
        latest_thinking = ""
        recent_tools = []
        for r in reversed(rows):
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

        return {
            "status": "working" if is_subproc_running else "idle",
            "markdown": "\n\n---\n\n".join(md_sections[-3:]),
            "terminal": "\n\n".join(term_logs[-4:]) if term_logs else f"Runtime: {runtime}",
            "thinking": latest_thinking[-1200:] if latest_thinking else "",
            "tool_calls": recent_tools[-6:],
            "telemetry": {"steps": len(rows), "input_tokens": 0, "cache_tokens": 0, "output_tokens": 0},
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
            "telemetry": {"steps": 0, "input_tokens": 0, "cache_tokens": 0, "output_tokens": 0},
        }

    log_dir = BRAIN_DIR / cid / ".system_generated" / "logs"
    full_file = log_dir / "transcript_full.jsonl"
    compact_file = log_dir / "transcript.jsonl"
    target_file = full_file if full_file.exists() else compact_file

    steps = read_tail_jsonl(target_file, max_bytes=650_000, max_steps=140)
    if not steps:
        return {
            "status": "working" if is_subproc_running else "idle",
            "markdown": f"*Konuşma (`{cid[:8]}`) hazır, çıktı bekleniyor...*",
            "terminal": f"Brain CID: {cid}\nNo steps recorded yet.",
            "thinking": "",
            "tool_calls": [],
            "telemetry": {"steps": 0, "input_tokens": 0, "cache_tokens": 0, "output_tokens": 0},
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


def sync_team_orchestration_doc(team_name: str, project_dir: str):
    """Generates and syncs TEAM_ORCHESTRATION.md in the project directory so all agents know the team, roles, and rules."""
    pdir = Path(project_dir) if project_dir else None
    if not pdir or not pdir.exists():
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

    # Check CLI tool availability
    bin_name = cmd[0]
    if not shutil.which(bin_name):
        return False, cid, f"Hata: '{bin_name}' CLI komutu bu sistemde kurulu değil."

    proc = await asyncio.create_subprocess_exec(
        *cmd,
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
            with get_db() as conn:
                conn.execute(
                    """
                    INSERT INTO agent_turns
                    (team_name, target, runtime, user_prompt, response_md, command_logs, status, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (team_name, target, runtime, prompt, stdout or "*Çıktı üretilmedi*", stderr, "DONE" if ok else "ERROR", now),
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
                        proc = await asyncio.create_subprocess_shell(
                            tool["command_or_prompt"],
                            cwd=wdir if Path(wdir).exists() else str(Path.home()),
                            stdout=asyncio.subprocess.PIPE,
                            stderr=asyncio.subprocess.PIPE,
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
            res = subprocess.run(["agy", "plugin", "list", "--json"], capture_output=True, text=True, check=False, timeout=5)
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
            res_m = subprocess.run(["agy", "mcp", "list"], capture_output=True, text=True, check=False, timeout=5)
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
