#!/usr/bin/env python3
"""
AGY-UI v3.0: Zero-Tmux Native Brain JSONL & SQLite Multi-Agent Orchestrator
- Pure Structured Markdown, Thinking & Tool Call Telemetry from Brain JSONL
- Atomic SQLite Persistence (~/.agy-teams/state.db)
- Scalable Tool, Skill, Persona & MCP Integration Hub
"""

import os
import sys
import json
import asyncio
import subprocess
import re
from pathlib import Path
from datetime import datetime
from aiohttp import web

# Ensure local directory is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import engine

HOST = "127.0.0.1"
PORT = 4444
# Windows'ta kullanıcı profili yazılamıyorsa engine %LOCALAPPDATA%\HiveForge'a düşer; aynı dizini kullan
BASE_DIR = engine.BASE_DIR
TEAMS_DIR = BASE_DIR / "teams"
STATIC_DIR = Path(__file__).resolve().parent / "static"


# ----------------- Dosya Kilitleri & Çakışma Bariyeri -----------------

def scan_team_locks(team_name: str, project_dir: str):
    locks = []
    team_lock_file = TEAMS_DIR / team_name / "locks.json"
    if team_lock_file.exists():
        try:
            data = json.loads(team_lock_file.read_text(encoding="utf-8"))
            for fpath, info in data.items():
                locks.append({
                    "file": fpath,
                    "agent": info.get("claimed_by", "unknown"),
                    "time": info.get("locked_at", ""),
                    "scope": "team",
                })
        except Exception:
            pass

    pdir = Path(project_dir) if project_dir else None
    if pdir and pdir.exists():
        subrepos = [pdir] + [p for p in pdir.iterdir() if p.is_dir() and not p.name.startswith(".")]
        for sub in subrepos[:15]:
            lf = sub / ".locks" / "locks.json"
            if lf.exists():
                try:
                    data = json.loads(lf.read_text(encoding="utf-8"))
                    for fpath, info in data.items():
                        locks.append({
                            "file": fpath,
                            "agent": info.get("claimed_by", "unknown"),
                            "time": info.get("locked_at", ""),
                            "scope": sub.name,
                        })
                except Exception:
                    pass
    return locks


# ----------------- Project Brain & Kanban Ayrıştırıcı -----------------

def extract_project_brain(project_dir: str, team_name: str):
    candidates = engine.team_memory_files(project_dir)
    candidates.append(TEAMS_DIR / team_name / "brain.json")

    sections = {}
    current_sec = "Genel Mimari"
    for c in candidates:
        if c.exists() and c.suffix == ".md":
            try:
                content = c.read_text(encoding="utf-8")
                for line in content.splitlines():
                    if line.startswith("## "):
                        current_sec = line.replace("## ", "").strip()
                        if current_sec not in sections:
                            sections[current_sec] = []
                    elif current_sec in sections:
                        sections[current_sec].append(line)
            except Exception:
                pass
    result = []
    for title, lines in sections.items():
        body = "\n".join(lines).strip()
        if body:
            result.append({"title": title, "content": body[:5000]})
    return result


def extract_kanban_tasks(project_dir: str, team_name: str):
    tasks = []
    candidates = engine.team_memory_files(project_dir)
    candidates.append(TEAMS_DIR / team_name / "tasks.json")

    for c in candidates:
        if c.exists() and c.suffix == ".json":
            try:
                data = json.loads(c.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    tasks.extend(data)
            except Exception:
                pass
        elif c.exists() and c.suffix == ".md":
            try:
                content = c.read_text(encoding="utf-8")
                for line in content.splitlines():
                    m = re.match(r"^\s*[-*]\s*\[([ xX/!~])\]\s*(.+)$", line)
                    if m:
                        flag = m.group(1).lower()
                        title = m.group(2).strip()
                        if flag == "x":
                            st = "done"
                        elif flag == "/":
                            st = "in_progress"
                        elif flag == "!":
                            st = "blocked"
                        else:
                            st = "todo"
                        tasks.append({"title": title, "status": st, "source": c.name})
            except Exception:
                pass
    return tasks[:35]


def get_team_agents(team_name: str):
    with engine.get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM agents WHERE team_name = ? ORDER BY aid ASC", (team_name,)
        ).fetchall()
        agents = []
        for idx, r in enumerate(rows):
            cid = r["cid"] or ""
            runtime = r["runtime"] if ("runtime" in r.keys() and r["runtime"]) else "agy"
            model = r["model"] if ("model" in r.keys() and r["model"]) else ""
            agents.append({
                "id": f"agent_{r['aid']}",
                "pane": idx,
                "aid": r["aid"],
                "name": r["name"],
                "role": r["role"],
                "target": r["target"],
                "cid": cid[:8] if cid else "new-agent",
                "full_cid": cid,
                "runtime": runtime,
                "model": model,
                "persona": r["persona"] or "",
                "effort": r["effort"] or "medium",
                "mode": r["mode"] or "auto",
                "workspace_dir": r["workspace_dir"] or "",
                "skills": json.loads(r["skills_json"] or "[]"),
                "tools": json.loads(r["tools_json"] or "[]"),
                "is_alive": True,
            })
        return agents


# ----------------- HTTP API Handlers -----------------

async def handle_index(request):
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return web.FileResponse(index_file)
    return web.Response(text="index.html not found", status=404)


async def handle_favicon(request):
    fav = STATIC_DIR / "favicon.svg"
    if fav.exists():
        return web.FileResponse(fav, headers={"Content-Type": "image/svg+xml"})
    return web.Response(status=404)


async def handle_logo(request):
    logo = STATIC_DIR / "logo.svg"
    if logo.exists():
        return web.FileResponse(logo, headers={"Content-Type": "image/svg+xml"})
    return web.Response(status=404)


async def api_list_teams(request):
    teams = []
    with engine.get_db() as conn:
        rows = conn.execute("SELECT * FROM teams ORDER BY name ASC").fetchall()
        for r in rows:
            ag_count = conn.execute(
                "SELECT COUNT(*) FROM agents WHERE team_name = ?", (r["name"],)
            ).fetchone()[0]
            teams.append({
                "name": r["name"],
                "role": r["lead_role"],
                "project_dir": r["project_dir"],
                "agent_count": ag_count,
                "is_running": True,  # Native headless engine is always online
            })
    return web.json_response({"success": True, "teams": teams})


async def api_get_team_info(request):
    team_name = request.match_info.get("name")
    with engine.get_db() as conn:
        team = conn.execute("SELECT * FROM teams WHERE name = ?", (team_name,)).fetchone()
        if not team:
            return web.json_response({"success": False, "error": f"Team '{team_name}' not found"}, status=404)

        project_dir = team["project_dir"]
        lead_cid = team["lead_cid"] or ""
        lead_runtime = team["lead_runtime"] if ("lead_runtime" in team.keys() and team["lead_runtime"]) else "agy"
        lead_info = {
            "id": "lead",
            "name": f"{team_name.title()} Tech Lead",
            "role": team["lead_role"],
            "target": "@lead",
            "cid": lead_cid[:8] if lead_cid else "lead-init",
            "full_cid": lead_cid,
            "runtime": lead_runtime,
            "persona": team["lead_persona"] or "",
            "effort": team["lead_effort"] or "high",
            "workspace_dir": project_dir,
        }

    agents = get_team_agents(team_name)
    locks = scan_team_locks(team_name, project_dir)
    tasks = extract_kanban_tasks(project_dir, team_name)
    brain_sections = extract_project_brain(project_dir, team_name)
    tokens = engine.get_team_token_analytics(team_name)

    return web.json_response({
        "success": True,
        "team": team_name,
        "engine": "native-jsonl-sqlite-v3",
        "is_running": True,
        "project_dir": project_dir,
        "lead": lead_info,
        "agents": agents,
        "locks": locks,
        "tasks": tasks,
        "brain": brain_sections,
        "tokens": tokens,
    })


async def api_get_team_tokens(request):
    team_name = request.match_info.get("name")
    data = engine.get_team_token_analytics(team_name)
    return web.json_response(data)


async def api_get_ecosystem(request):
    eco = engine.discover_agy_ecosystem()
    return web.json_response({"success": True, **eco})


async def api_configure_agent(request):
    """Updates an agent's skills, tools, persona, effort, workspace_dir, role, or CID in SQLite."""
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"success": False, "error": "Invalid JSON"}, status=400)

    team = data.get("team")
    target = data.get("target")
    if not team or not target:
        return web.json_response({"success": False, "error": "team and target are required"}, status=400)

    with engine.get_db() as conn:
        if target in ("@lead", "lead"):
            if "role" in data:
                conn.execute("UPDATE teams SET lead_role = ? WHERE name = ?", (data["role"], team))
            if "cid" in data:
                conn.execute("UPDATE teams SET lead_cid = ? WHERE name = ?", (data["cid"].strip(), team))
            if "persona" in data:
                conn.execute("UPDATE teams SET lead_persona = ? WHERE name = ?", (data["persona"], team))
            if "effort" in data:
                conn.execute("UPDATE teams SET lead_effort = ? WHERE name = ?", (data["effort"], team))
            if "runtime" in data:
                conn.execute("UPDATE teams SET lead_runtime = ? WHERE name = ?", (data["runtime"], team))
            return web.json_response({"success": True, "message": "Tech Lead yapılandırması güncellendi."})

        row = conn.execute(
            "SELECT * FROM agents WHERE team_name = ? AND target = ?", (team, target)
        ).fetchone()
        if not row:
            return web.json_response({"success": False, "error": f"Ajan bulunamadı: {target}"}, status=404)

        name = data.get("name", row["name"])
        role = data.get("role", row["role"])
        cid = data.get("cid", row["cid"])
        runtime = data.get("runtime", row["runtime"] if "runtime" in row.keys() else "agy")
        model = data.get("model", row["model"] if "model" in row.keys() else "")
        persona = data.get("persona", row["persona"])
        effort = data.get("effort", row["effort"])
        mode = data.get("mode", row["mode"])
        workspace_dir = data.get("workspace_dir", row["workspace_dir"])
        skills = data.get("skills", json.loads(row["skills_json"] or "[]"))
        tools = data.get("tools", json.loads(row["tools_json"] or "[]"))

        conn.execute(
            """
            UPDATE agents
            SET name = ?, role = ?, cid = ?, runtime = ?, model = ?, persona = ?, effort = ?, mode = ?,
                workspace_dir = ?, skills_json = ?, tools_json = ?
            WHERE team_name = ? AND target = ?
            """,
            (
                name,
                role,
                cid.strip(),
                runtime,
                model.strip(),
                persona,
                effort,
                mode,
                workspace_dir.strip(),
                json.dumps(skills),
                json.dumps(tools),
                team,
                target,
            ),
        )
        engine.export_agents_json(conn, team)
    engine.sync_team_orchestration_doc(team)

    return web.json_response({"success": True, "message": f"{name} ({target}) yapılandırması kaydedildi."})


async def api_create_tool(request):
    """Registers a new reusable custom tool in SQLite tools_registry."""
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"success": False, "error": "Invalid JSON"}, status=400)

    tid = re.sub(r"[^a-z0-9_-]", "-", data.get("id", "").strip().lower()) or f"tool-{int(datetime.now().timestamp())}"
    name = data.get("name", "").strip()
    category = data.get("category", "custom").strip()
    description = data.get("description", "").strip()
    tool_type = data.get("tool_type", "shell_context").strip()
    command_or_prompt = data.get("command_or_prompt", "").strip()
    icon = data.get("icon", "🔧").strip() or "🔧"

    if not name or not command_or_prompt:
        return web.json_response({"success": False, "error": "Araç adı ve komut/şablon zorunludur."}, status=400)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with engine.get_db() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO tools_registry
            (id, name, category, description, tool_type, command_or_prompt, icon, is_builtin, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)
            """,
            (tid, name, category, description, tool_type, command_or_prompt, icon, now),
        )
    engine._ECOSYSTEM_CACHE["ts"] = 0
    return web.json_response({"success": True, "id": tid, "name": name})


async def api_delete_tool(request):
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"success": False, "error": "Invalid JSON"}, status=400)
    tid = data.get("id", "")
    with engine.get_db() as conn:
        conn.execute("DELETE FROM tools_registry WHERE id = ? AND is_builtin = 0", (tid,))
    engine._ECOSYSTEM_CACHE["ts"] = 0
    return web.json_response({"success": True})


async def api_run_tool(request):
    """Runs a tool either standalone (preview output) or dispatches its result to an agent."""
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"success": False, "error": "Invalid JSON"}, status=400)

    team = data.get("team") or engine.default_team()
    target = data.get("target", "@lead")
    tool_id = data.get("tool_id")
    prompt = data.get("prompt", "__TOOL_ONLY__")

    if not tool_id:
        return web.json_response({"success": False, "error": "tool_id is required"}, status=400)

    res = await engine.dispatch_message(
        team_name=team,
        target=target,
        message=prompt,
        sender="ToolHub",
        msg_type="tool",
        tool_id=tool_id,
    )
    return web.json_response(res)


async def api_get_locks(request):
    team_name = request.match_info.get("name")
    with engine.get_db() as conn:
        team = conn.execute("SELECT project_dir FROM teams WHERE name = ?", (team_name,)).fetchone()
        if not team:
            return web.json_response({"success": False, "error": "Team not found"}, status=404)
        locks = scan_team_locks(team_name, team["project_dir"])
    return web.json_response({"success": True, "locks": locks})


async def api_get_brain(request):
    team_name = request.match_info.get("name")
    with engine.get_db() as conn:
        team = conn.execute("SELECT project_dir FROM teams WHERE name = ?", (team_name,)).fetchone()
        if not team:
            return web.json_response({"success": False, "error": "Team not found"}, status=404)
        sections = extract_project_brain(team["project_dir"], team_name)
    return web.json_response({"success": True, "team": team_name, "sections": sections})


async def api_get_tasks(request):
    team_name = request.match_info.get("name")
    with engine.get_db() as conn:
        team = conn.execute("SELECT project_dir FROM teams WHERE name = ?", (team_name,)).fetchone()
        if not team:
            return web.json_response({"success": False, "error": "Team not found"}, status=404)
        tasks = extract_kanban_tasks(team["project_dir"], team_name)
    return web.json_response({"success": True, "tasks": tasks})


async def api_get_ledger(request):
    team_name = request.match_info.get("name")
    include_closed = request.query.get("all") in ("1", "true")
    return web.json_response({"success": True, "tasks": engine.list_tasks(team_name, include_closed=include_closed)})


async def api_review_task(request):
    try:
        data = await request.json()
        task_id = int(data.get("id"))
    except Exception:
        return web.json_response({"success": False, "error": "Geçersiz istek (team, id, decision gerekli)"}, status=400)
    decision = str(data.get("decision", "")).lower()
    if decision not in ("approve", "reject", "onay", "ret"):
        return web.json_response({"success": False, "error": "decision: approve|reject"}, status=400)
    res = await engine.review_task(
        data.get("team", ""), task_id, decision in ("approve", "onay"), data.get("note", ""), data.get("sender") or "User"
    )
    return web.json_response(res, status=200 if res.get("success") else 400)


async def api_send_note(request):
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"success": False, "error": "Invalid JSON"}, status=400)

    team = data.get("team")
    target = data.get("target")
    sender = data.get("sender", "Tech Lead")
    note = data.get("note")

    if not team or not target or not note:
        return web.json_response({"success": False, "error": "team, target, note are required"}, status=400)

    res = await engine.dispatch_message(
        team_name=team,
        target=target,
        message=note,
        sender=sender,
        msg_type="note",
    )
    return web.json_response({**res, "sender": sender, "target": target, "note": note})


async def api_create_team(request):
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"success": False, "error": "Invalid JSON"}, status=400)

    name = re.sub(r"[^a-z0-9_-]", "-", data.get("name", "").strip().lower())
    project_dir = data.get("project_dir", "").strip()
    role = data.get("role", "Genel Yazılım Takım Lideri").strip()

    if not name:
        return web.json_response({"success": False, "error": "Takım adı zorunludur"}, status=400)

    if not project_dir:
        project_dir = str(engine.default_projects_root() / name)
    Path(project_dir).mkdir(parents=True, exist_ok=True)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    tdir = TEAMS_DIR / name
    tdir.mkdir(parents=True, exist_ok=True)
    log_dir = Path(project_dir) / ".team_orchestration" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    (tdir / "config.env").write_text(
        f'TEAM_NAME="{name}"\nPROJECT_DIR="{project_dir}"\nSESSION_NAME="agy-{name}"\n'
        f'LEAD_ROLE="{role}"\nLOG_DIR="{log_dir}"\nCREATED_AT="{now}"\n',
        encoding="utf-8",
    )

    with engine.get_db() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO teams (name, project_dir, session_name, lead_role, lead_cid, created_at)
            VALUES (?, ?, ?, ?, '', ?)
            """,
            (name, project_dir, f"agy-{name}", role, now),
        )
        default_agents = [
            (1, "Backend & API", "Backend & Database Specialist", "@backend"),
            (2, "Frontend & UI", "Frontend & Design Specialist", "@frontend"),
            (3, "QA & Security", "Test & Security Auditor", "@qa"),
            (4, "DevOps & Infra", "Build & Deployment Engineer", "@devops"),
        ]
        for aid, aname, arole, atarget in default_agents:
            conn.execute(
                """
                INSERT OR IGNORE INTO agents
                (team_name, aid, name, role, target, cid, workspace_dir, skills_json, tools_json, pane, created_at)
                VALUES (?, ?, ?, ?, ?, '', ?, '[]', '["git-status-diff"]', ?, ?)
                """,
                (name, aid, aname, arole, atarget, project_dir, aid - 1, now),
            )
        engine.export_agents_json(conn, name)
        engine.sync_team_orchestration_doc(name, project_dir)

    return web.json_response({"success": True, "team": name, "project_dir": project_dir})


async def api_add_agent(request):
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"success": False, "error": "Invalid JSON"}, status=400)

    team = data.get("team")
    name = data.get("name", "").strip()
    role = data.get("role", "").strip()
    target = data.get("target", "").strip()
    persona = data.get("persona", "").strip()
    effort = data.get("effort", "medium").strip()
    workspace_dir = data.get("workspace_dir", "").strip()
    skills = data.get("skills", [])
    tools = data.get("tools", ["git-status-diff"])
    cid = data.get("cid", "").strip()
    runtime = data.get("runtime", "agy").strip() or "agy"
    model = data.get("model", "").strip()

    if not team:
        return web.json_response({"success": False, "error": "team is required"}, status=400)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with engine.get_db() as conn:
        t_row = conn.execute("SELECT project_dir FROM teams WHERE name = ?", (team,)).fetchone()
        if not t_row:
            return web.json_response({"success": False, "error": f"Team '{team}' not found"}, status=404)

        max_aid = conn.execute(
            "SELECT COALESCE(MAX(aid), 0) FROM agents WHERE team_name = ?", (team,)
        ).fetchone()[0]
        new_aid = max_aid + 1

        if not name:
            name = f"Agent {new_aid}"
        if not role:
            role = f"Specialist Worker #{new_aid}"
        if not target:
            slug = re.sub(r"[^a-z0-9]", "", name.lower())[:10] or str(new_aid)
            target = f"@{slug}"
        elif not target.startswith("@"):
            target = f"@{target}"

        # Ensure unique target
        existing_t = conn.execute(
            "SELECT 1 FROM agents WHERE team_name = ? AND target = ?", (team, target)
        ).fetchone()
        if existing_t:
            target = f"{target}{new_aid}"

        if not workspace_dir:
            workspace_dir = t_row["project_dir"]

        conn.execute(
            """
            INSERT INTO agents
            (team_name, aid, name, role, target, cid, runtime, model, persona, effort, mode, workspace_dir, skills_json, tools_json, pane, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'auto', ?, ?, ?, ?, ?)
            """,
            (
                team,
                new_aid,
                name,
                role,
                target,
                cid,
                runtime,
                model,
                persona,
                effort,
                workspace_dir,
                json.dumps(skills),
                json.dumps(tools),
                new_aid - 1,
                now,
            ),
        )
        engine.export_agents_json(conn, team)
    engine.sync_team_orchestration_doc(team)

    return web.json_response({
        "success": True,
        "aid": new_aid,
        "name": name,
        "role": role,
        "target": target,
    })


async def api_remove_agent(request):
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"success": False, "error": "Invalid JSON"}, status=400)

    team = data.get("team")
    target = str(data.get("target", "")).strip()
    if not team or not target:
        return web.json_response({"success": False, "error": "team and target are required"}, status=400)

    clean_t = target.lstrip("@").lower()
    with engine.get_db() as conn:
        rows = conn.execute("SELECT * FROM agents WHERE team_name = ?", (team,)).fetchall()
        found = None
        for r in rows:
            if (
                r["target"].lower() == target.lower()
                or r["target"].lstrip("@").lower() == clean_t
                or r["name"].lower() == target.lower()
                or str(r["aid"]) == clean_t
            ):
                found = r
                break
        if not found:
            return web.json_response({"success": False, "error": f"Ajan bulunamadı: {target}"}, status=404)

        conn.execute("DELETE FROM agents WHERE id = ?", (found["id"],))
        # Re-normalize aid sequence cleanly without losing CIDs!
        remaining = conn.execute(
            "SELECT id FROM agents WHERE team_name = ? ORDER BY aid ASC", (team,)
        ).fetchall()
        for idx, rem in enumerate(remaining):
            conn.execute("UPDATE agents SET aid = ?, pane = ? WHERE id = ?", (idx + 1, idx, rem["id"]))
        engine.export_agents_json(conn, team)
    engine.sync_team_orchestration_doc(team)

    return web.json_response({"success": True, "removed": found["name"], "target": found["target"]})


async def api_dispatch(request):
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"success": False, "error": "Invalid JSON"}, status=400)

    team = data.get("team")
    target = data.get("target")
    message = data.get("message")
    tool_id = data.get("tool_id")

    if not team or not target or not message:
        return web.json_response({"success": False, "error": "team, target, message are required"}, status=400)

    res = await engine.dispatch_message(
        team_name=team,
        target=target,
        message=message,
        sender=data.get("sender") or "User",
        msg_type="dispatch",
        tool_id=tool_id,
    )
    return web.json_response(res)


async def api_restore(request):
    """Syncs SQLite state and refreshes all Brain JSONL links."""
    engine.sync_and_migrate()
    return web.json_response({"success": True, "output": "Tüm ajan konuşma kimlikleri (Brain JSONL) ve SQLite durumları senkronize edildi."})


# ----------------- WebSocket Real-Time Brain JSONL Streamer -----------------

async def websocket_handler(request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)

    team_name = request.query.get("team") or engine.default_team()

    last_hashes = {}

    try:
        while not ws.closed:
            with engine.get_db() as conn:
                team = conn.execute("SELECT * FROM teams WHERE name = ?", (team_name,)).fetchone()
                if not team:
                    await ws.send_json({"type": "error", "message": f"Team '{team_name}' not found"})
                    await ws.close()
                    return ws
                lead_cid = team["lead_cid"] or ""

            current_agents = get_team_agents(team_name)

            for ag in current_agents:
                cid = ag["full_cid"]
                card_id = ag["id"]
                task_key = f"{team_name}:{ag['target']}"
                snap = engine.read_brain_snapshot(
                    cid,
                    task_key=task_key,
                    runtime=ag.get("runtime", "agy"),
                    team_name=team_name,
                    target=ag["target"],
                    model=ag.get("model", ""),
                )

                state_sig = f"{snap['status']}|{len(snap['markdown'])}|{len(snap['terminal'])}|{snap['telemetry']['steps']}|{snap['telemetry'].get('context_tokens',0)}|{snap['telemetry'].get('cum_total_tokens',0)}|{ag['name']}|{len(ag['tools'])}|{len(ag['skills'])}|{ag['runtime']}|{ag['model']}"
                if last_hashes.get(card_id) != state_sig:
                    last_hashes[card_id] = state_sig
                    await ws.send_json({
                        "type": "pane_snapshot",
                        "agent": ag["aid"],
                        "pane": ag["pane"],
                        "card_id": card_id,
                        "name": ag["name"],
                        "role": ag["role"],
                        "target": ag["target"],
                        "runtime": ag["runtime"],
                        "model": ag["model"],
                        "cid": ag["cid"],
                        "full_cid": cid,
                        "persona": ag["persona"],
                        "effort": ag["effort"],
                        "workspace_dir": ag["workspace_dir"],
                        "skills": ag["skills"],
                        "tools": ag["tools"],
                        "status": snap["status"],
                        "content": snap["markdown"],
                        "terminal": snap["terminal"],
                        "thinking": snap["thinking"],
                        "tool_calls": snap["tool_calls"],
                        "telemetry": snap["telemetry"],
                    })

            # Lead Snapshot from Brain JSONL
            lead_snap = engine.read_brain_snapshot(
                lead_cid,
                task_key=f"{team_name}:@lead",
                runtime=team["lead_runtime"] or "agy",
                team_name=team_name,
                target="@lead",
            )
            lead_sig = f"{team['lead_runtime']}|{lead_snap['status']}|{len(lead_snap['markdown'])}|{len(lead_snap['terminal'])}|{lead_snap['telemetry']['steps']}|{lead_snap['telemetry'].get('context_tokens',0)}|{lead_snap['telemetry'].get('cum_total_tokens',0)}"
            if last_hashes.get("lead") != lead_sig:
                last_hashes["lead"] = lead_sig
                await ws.send_json({
                    "type": "lead_snapshot",
                    "runtime": team["lead_runtime"] or "agy",
                    "cid": lead_cid[:8] if lead_cid else "lead",
                    "full_cid": lead_cid,
                    "status": lead_snap["status"],
                    "content": lead_snap["markdown"],
                    "terminal": lead_snap["terminal"],
                    "thinking": lead_snap["thinking"],
                    "tool_calls": lead_snap["tool_calls"],
                    "telemetry": lead_snap["telemetry"],
                })

            ledger = engine.list_tasks(team_name)
            ledger_sig = "|".join(f"{t['id']}:{t['status']}:{t['tokens']}" for t in ledger)
            if last_hashes.get("ledger") != ledger_sig:
                last_hashes["ledger"] = ledger_sig
                await ws.send_json({"type": "tasks_snapshot", "tasks": ledger})

            # Team-wide live token analytics snapshot
            tok_analytics = engine.get_team_token_analytics(team_name)
            tok_sig = f"{tok_analytics['total_cum_tokens']}|{tok_analytics['total_context_tokens']}"
            if last_hashes.get("tokens") != tok_sig:
                last_hashes["tokens"] = tok_sig
                await ws.send_json({
                    "type": "tokens_snapshot",
                    "tokens": tok_analytics,
                })

            await asyncio.sleep(1.0)
    except asyncio.CancelledError:
        pass
    finally:
        await ws.close()

    return ws


LOCAL_HOSTNAMES = {"127.0.0.1", "localhost"}


@web.middleware
async def local_only_middleware(request, handler):
    """Blocks cross-site requests (CSRF / DNS rebinding): agents run with full shell access."""
    from urllib.parse import urlsplit
    host = request.host or ""
    if urlsplit(f"//{host}").hostname not in LOCAL_HOSTNAMES:
        return web.json_response({"success": False, "error": "Forbidden host"}, status=403)
    origin = request.headers.get("Origin")
    if origin is not None and urlsplit(origin).netloc != host:
        return web.json_response({"success": False, "error": "Forbidden origin"}, status=403)
    return await handler(request)


def create_app():
    engine.sync_and_migrate()
    with engine.get_db() as conn:
        # turns started by a previous server process can no longer be tracked
        conn.execute("UPDATE dispatch_queue SET status = 'stale' WHERE status IN ('queued', 'running')")
    app = web.Application(middlewares=[local_only_middleware])
    app.router.add_get("/", handle_index)
    app.router.add_get("/favicon.ico", handle_favicon)
    app.router.add_get("/favicon.svg", handle_favicon)
    app.router.add_get("/logo.svg", handle_logo)
    app.router.add_get("/api/teams", api_list_teams)
    app.router.add_get("/api/ecosystem", api_get_ecosystem)
    app.router.add_get("/api/team/{name}", api_get_team_info)
    app.router.add_get("/api/team/{name}/locks", api_get_locks)
    app.router.add_get("/api/team/{name}/tasks", api_get_tasks)
    app.router.add_get("/api/team/{name}/brain", api_get_brain)
    app.router.add_get("/api/team/{name}/tokens", api_get_team_tokens)
    app.router.add_post("/api/agent/configure", api_configure_agent)
    app.router.add_post("/api/agent/run-tool", api_run_tool)
    app.router.add_post("/api/tools/create", api_create_tool)
    app.router.add_post("/api/tools/delete", api_delete_tool)
    app.router.add_post("/api/note", api_send_note)
    app.router.add_get("/api/team/{name}/ledger", api_get_ledger)
    app.router.add_post("/api/task/review", api_review_task)
    app.router.add_post("/api/team/create", api_create_team)
    app.router.add_post("/api/team/add-agent", api_add_agent)
    app.router.add_post("/api/team/remove-agent", api_remove_agent)
    app.router.add_post("/api/dispatch", api_dispatch)
    app.router.add_post("/api/restore", api_restore)
    app.router.add_get("/ws", websocket_handler)
    app.router.add_static("/static/", path=str(STATIC_DIR), name="static")
    return app


if __name__ == "__main__":
    port = PORT
    if len(sys.argv) > 1 and sys.argv[1].isdigit():
        port = int(sys.argv[1])
    if os.name == "nt":
        # Windows konsolu (cp1254/cp857) emoji ve Türkçe karakterlerde çökmesin
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass
    app = create_app()
    print("==================================================================")
    print(f"🚀 AGY-VIBE v3.0 (Zero-Tmux Native Brain JSONL + SQLite): http://{HOST}:{port}")
    print("==================================================================")
    web.run_app(app, host=HOST, port=port)
