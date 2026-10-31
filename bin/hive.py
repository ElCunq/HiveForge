#!/usr/bin/env python3
# ==============================================================================
# HiveForge: Cross-platform (Windows dahil) CLI
# bin/team (bash) ile aynı komutları sunar; Windows'ta kökteki hiveforge.bat üzerinden çalışır.
# Linux/macOS'ta bin/team kullanılmaya devam edilebilir.
# ==============================================================================
import os
import sys
import json
import time
import socket
import subprocess
import webbrowser
import urllib.error
import urllib.request
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ENGINE_DIR))
os.environ.setdefault("ENGINE_DIR", str(ENGINE_DIR))

import engine as _engine_mod  # noqa: E402  (BASE_DIR'i engine ile aynı kuralla belirle)

BASE_DIR = _engine_mod.BASE_DIR
TEAMS_DIR = _engine_mod.TEAMS_DIR
API_URL = os.environ.get("AGY_API_URL", "http://127.0.0.1:4444").rstrip("/")

IS_WINDOWS = os.name == "nt"

if IS_WINDOWS:
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    os.system("")  # Windows konsolunda ANSI renk kodlarını etkinleştirir


def _engine():
    return _engine_mod


# ----------------------------- Sunucu yönetimi -----------------------------

def _port() -> int:
    tail = API_URL.rsplit(":", 1)[-1].split("/")[0]
    return int(tail) if tail.isdigit() else 4444


def server_is_up() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", _port()), timeout=0.5):
            return True
    except OSError:
        return False


def _systemd(action: str) -> bool:
    """Linux: if install.sh set up hiveforge.service, let systemd own the server (a manual copy would fight it for the port)."""
    if IS_WINDOWS or not (Path.home() / ".config/systemd/user/hiveforge.service").exists():
        return False
    return subprocess.run(["systemctl", "--user", action, "hiveforge.service"], capture_output=True).returncode == 0


def ensure_server_running() -> None:
    if server_is_up():
        return
    if _systemd("start"):
        for _ in range(40):
            if server_is_up():
                return
            time.sleep(0.25)
    log_dir = BASE_DIR / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = open(log_dir / "server.log", "ab")
    py = sys.executable
    kwargs = {"cwd": str(ENGINE_DIR), "stdout": log_file, "stderr": subprocess.STDOUT, "stdin": subprocess.DEVNULL}
    if IS_WINDOWS:
        pyw = Path(py).with_name("pythonw.exe")
        if pyw.exists():
            py = str(pyw)
        kwargs["creationflags"] = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen([py, str(ENGINE_DIR / "server.py"), str(_port())], **kwargs)
    for _ in range(40):
        if server_is_up():
            return
        time.sleep(0.25)
    print(f"[UYARI] Sunucu başlatılamadı. Log: {log_dir / 'server.log'}")


def _windows_server_pids(port: int) -> set:
    """Portu dinleyen süreç + bu kurulumun server.py'sini çalıştıran tüm python süreçleri (venv başlatıcısı dahil)."""
    pids = set()
    out = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True, errors="ignore").stdout
    for ln in out.splitlines():
        parts = ln.split()
        if len(parts) >= 5 and parts[1].endswith(f":{port}") and parts[3].upper() in ("LISTENING", "DINLIYOR", "DİNLİYOR"):
            pids.add(parts[-1])
    server_py = str(ENGINE_DIR / "server.py").replace("'", "''")
    ps = (
        "Get-CimInstance Win32_Process -Filter \"Name like 'python%'\" | "
        f"Where-Object {{ $_.CommandLine -and $_.CommandLine.Contains('{server_py}') }} | "
        "ForEach-Object { $_.ProcessId }"
    )
    out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, errors="ignore").stdout
    pids.update(x.strip() for x in out.split() if x.strip().isdigit())
    pids.discard("0")
    return pids


def stop_server() -> None:
    port = _port()
    if IS_WINDOWS:
        pids = _windows_server_pids(port)
        if not pids and not server_is_up():
            print("[BİLGİ] Sunucu zaten çalışmıyor.")
            return
        for pid in pids:
            subprocess.run(["taskkill", "/PID", pid, "/T", "/F"], capture_output=True)
    else:
        if not server_is_up():
            print("[BİLGİ] Sunucu zaten çalışmıyor.")
            return
        _systemd("stop")
        if server_is_up():
            subprocess.run(["fuser", "-k", f"{port}/tcp"], capture_output=True)
    for _ in range(20):
        if not server_is_up():
            print("[OK] Sunucu durduruldu.")
            return
        time.sleep(0.25)
    print(f"[UYARI] Sunucu hâlâ {port} portunda yanıt veriyor; Görev Yöneticisi'nden python süreçlerini kontrol edin.")


def api_post(path: str, payload: dict) -> dict:
    req = urllib.request.Request(
        f"{API_URL}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ----------------------------- Komutlar -----------------------------

HELP = """================================================================================
  HIVEFORGE: Multi-CLI Agent Team Orchestration CLI (Linux · macOS · Windows)
================================================================================
Kullanım (Windows'ta 'hive' / 'team' yerine 'hiveforge' yazın):
  hive / team                  # Kokpiti açar ve anlık durum tablosunu gösterir
  hive stop                    # Arka plandaki HiveForge sunucusunu durdurur
  hive server                  # Sunucuyu bu pencerede (ön planda) çalıştırır
  team list                    # Kayıtlı tüm takımları listeler
  team agents      [takım-adı] # Takımdaki ajanları, CLI motorlarını, bağlam ve token kullanımını listeler
  team tokens      [takım-adı] # Token harcamalarını, kalan bağlamı ve ajan dökümünü gösterir
  team create      <takım> [proje-dizini] [--role "Rol"]
  team open        <@hedef> [takım]  # İlgili ajanın interaktif oturumuna girer
  team watch       [takım] [target]  # Canlı Markdown, Düşünce ve Araç akışını izler
  team dispatch    <takım> <@hedef> <mesaj>  # Görev iletir
  team note        <takım> <@hedef> [--from <ajan>] <not>  # /btw asenkron not iletir
  team tasks       <takım> [--all]           # Görev kayıtları (durum, token maliyeti)
  team review      <takım> <id> onay|ret ["not"]  # Biten görevi denetle (ret + not = ajana geri gönder)
  team deploy      <takım> [--tasks 12,13] -- <komut>  # Sadece lead: sıralı deploy, onaylı görevleri işaretler
  team deploys     <takım>                   # Deploy geçmişi
  team lock        <takım> <dosya...>        # Dosyaları kilitle (görev turu bitince otomatik açılır)
  team unlock      <takım> [dosya...]        # Kilitlerini aç (dosya verilmezse hepsi)
  team locks       <takım>                   # Aktif kilitler
  team ask-user    <takım> "soru"            # Kullanıcıya soru (cevap soran ajana not olarak döner)
  team tell-user   <takım> "mesaj"           # Kullanıcıya bilgi (arayüz gelen kutusu + bildirim)
  team logs        <takım> [hedef]           # Ajan çıktısını görüntüler
  team tools       [list | run <takım> <hedef> <araç-id>]
  team add-agent   <takım> --name "..." --role "..." [--runtime agy|claude|codex|aider|ollama] [--model "..."]
  team remove-agent <takım> <@hedef>
  (Not: 'tmux' modu Windows'ta yoktur; yerine 'watch' kullanın.)
================================================================================"""


def cmd_list(_args):
    engine = _engine()
    engine.sync_and_migrate()
    print("=" * 110)
    print(f"{'TAKIM ADI':<15} {'MOTOR DURUMU':<16} {'AJAN':<8} {'LİDER ROLÜ':<32} {'PROJE DİZİNİ'}")
    print("=" * 110)
    with engine.get_db() as conn:
        for t in conn.execute("SELECT * FROM teams ORDER BY name ASC").fetchall():
            cnt = conn.execute("SELECT COUNT(*) FROM agents WHERE team_name=?", (t["name"],)).fetchone()[0]
            print(f"{t['name']:<15} {'🟢 NATIVE READY':<16} {cnt:<8} {(t['lead_role'] or '')[:30]:<32} {t['project_dir'] or ''}")
    print("=" * 110)


def _fmt_tokens(n):
    if n is None:
        return "0"
    n = float(n)
    if abs(n) >= 1_000_000_000:
        return f"{n/1_000_000_000:.1f}B"
    if abs(n) >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if abs(n) >= 1_000:
        return f"{n/1_000:.1f}k"
    return str(int(n))


def cmd_agents(args):
    engine = _engine()
    tname = args[0] if args else _engine().default_team()
    engine.sync_and_migrate()
    with engine.get_db() as conn:
        team = conn.execute("SELECT * FROM teams WHERE name=?", (tname,)).fetchone()
        if not team:
            print(f"[HATA] '{tname}' takımı bulunamadı!")
            return 1
        lcid = team["lead_cid"] or ""
        lruntime = team["lead_runtime"] if "lead_runtime" in team.keys() and team["lead_runtime"] else "agy"
        lsnap = engine.read_brain_snapshot(lcid, f"{tname}:@lead")
        ltel = lsnap.get("telemetry", {})
        lctx = f"{_fmt_tokens(ltel.get('context_tokens', 0))} ({_fmt_tokens(ltel.get('remaining_tokens', 0))} boş)"
        lcum = _fmt_tokens(ltel.get("cum_total_tokens", 0))

        print("=" * 135)
        print(f"TAKIM: {tname.upper()} | Proje Dizini: {team['project_dir']}")
        print(f"TECH LEAD (@lead) | CLI: {lruntime.upper():<7} | CID: {lcid[:8] if lcid else 'new':<8} | Durum: {lsnap['status'].upper():<8} | Bağlam: {lctx} | Harcanan: {lcum}")
        print("-" * 135)
        print(f"{'ID':<4} {'HEDEF':<10} {'CLI':<8} {'AJAN ADI':<22} {'DURUM':<9} {'BAĞLAM / KALAN':<19} {'HARCANAN':<11} {'ARAÇ & SKILL'}")
        print("-" * 135)
        for r in conn.execute("SELECT * FROM agents WHERE team_name=? ORDER BY aid ASC", (tname,)).fetchall():
            cid = r["cid"] or ""
            rt = r["runtime"] if "runtime" in r.keys() and r["runtime"] else "agy"
            snap = engine.read_brain_snapshot(cid, f"{tname}:{r['target']}")
            tools = json.loads(r["tools_json"] or "[]")
            skills = json.loads(r["skills_json"] or "[]")
            badge = f"{len(tools)} araç, {len(skills)} skill"
            tel = snap.get("telemetry", {})
            ctx = f"{_fmt_tokens(tel.get('context_tokens', 0))} ({_fmt_tokens(tel.get('remaining_tokens', 0))} boş)"
            cum = _fmt_tokens(tel.get("cum_total_tokens", 0))
            print(f"#{r['aid']:<3} {r['target']:<10} {rt.upper():<8} {r['name'][:21]:<22} {snap['status'].upper():<9} {ctx:<19} {cum:<11} {badge}")
        print("=" * 135)
    return 0


def cmd_tokens(args):
    engine = _engine()
    tname = args[0] if args else _engine().default_team()
    engine.sync_and_migrate()
    analytics = engine.get_team_token_analytics(tname)
    if "error" in analytics:
        print(f"[HATA] {analytics['error']}")
        return 1

    print("=" * 115)
    print(f"HIVEFORGE TOKEN TELEMETRİSİ & KAYNAK YÖNETİMİ — TAKIM: {tname.upper()}")
    print("=" * 115)
    print(f"  Toplam Harcanan:   {_fmt_tokens(analytics['total_tokens']):<10} (Giriş: {_fmt_tokens(analytics['total_input_tokens'])}, Çıkış: {_fmt_tokens(analytics['total_output_tokens'])})")
    print(f"  Aktif Bağlam:      {_fmt_tokens(analytics['total_context_tokens'])} / {_fmt_tokens(analytics['total_context_limit'])} (%{analytics['total_context_pct']} Doluluk)")
    print(f"  Kalan Kapasite:    {_fmt_tokens(analytics['total_remaining_tokens']):<10} (Tüm ajanların serbest bağlam toplamı)")
    print(f"  Önbellek İsabeti:  %{analytics['cache_hit_pct']} (Tasarruf edilen: {_fmt_tokens(analytics['total_cache_tokens'])})")
    top = analytics.get("top_consumer")
    if top:
        print(f"  En Yüksek Tüketim: {top['target']} ({top['name']}) -> {_fmt_tokens(top['cum_total_tokens'])} (%{top['pct_of_team_tokens']})")
    print("-" * 115)
    print(f"{'HEDEF':<9} {'CLI':<8} {'AJAN ADI':<22} {'AKTİF BAĞLAM':<20} {'KALAN KAPASİTE':<16} {'KÜMÜLATİF':<14} {'PAY'}")
    print("-" * 115)
    for ag in analytics.get("agents", []):
        ctx_str = f"{_fmt_tokens(ag['context_tokens'])} / {_fmt_tokens(ag['context_limit'])} (%{ag['context_pct']})"
        rem_str = _fmt_tokens(ag['remaining_tokens'])
        cum_str = _fmt_tokens(ag['cum_total_tokens'])
        pay_str = f"%{ag['pct_of_team_tokens']}"
        print(f"{ag['target']:<9} {ag['runtime'].upper():<8} {ag['name'][:21]:<22} {ctx_str:<20} {rem_str:<16} {cum_str:<14} {pay_str}")
    print("=" * 115)
    return 0


def _parse_flags(args, mapping):
    out, rest, i = {}, [], 0
    while i < len(args):
        key = mapping.get(args[i])
        if key and i + 1 < len(args):
            out[key] = args[i + 1]
            i += 2
        else:
            rest.append(args[i])
            i += 1
    return out, rest


def cmd_create(args):
    if not args:
        print('Kullanım: team create <takım-adı> [proje-dizini] [--role "Rol"]')
        return 1
    flags, rest = _parse_flags(args[1:], {"--role": "role"})
    ensure_server_running()
    res = api_post("/api/team/create", {
        "name": args[0],
        "project_dir": rest[0] if rest else "",
        "role": flags.get("role", "Genel Yazılım Takım Lideri (Tech Lead)"),
    })
    if res.get("success"):
        print(f"[OK] '{args[0]}' takımı oluşturuldu! ({res.get('project_dir')})")
        return 0
    print(f"[HATA] {res.get('error')}")
    return 1


def cmd_add_agent(args):
    if not args:
        print('Kullanım: team add-agent <takım> --name "İsim" --role "Rol" [--target "@tag"] [--runtime agy|claude|codex|aider|ollama] [--model "..."]')
        return 1
    flags, _ = _parse_flags(args[1:], {
        "--name": "name", "-n": "name", "--role": "role", "-r": "role", "--target": "target", "-t": "target",
        "--runtime": "runtime", "--model": "model", "-m": "model", "--dir": "dir", "-d": "dir",
        "--skills": "skills", "-s": "skills", "--tools": "tools", "--persona": "persona", "-p": "persona",
        "--effort": "effort", "-e": "effort", "--cid": "cid",
    })
    runtime = flags.get("runtime", "agy")
    payload = {
        "team": args[0],
        "name": flags.get("name", ""),
        "role": flags.get("role", ""),
        "target": flags.get("target", ""),
        "runtime": runtime,
        "model": flags.get("model", ""),
        "workspace_dir": flags.get("dir", ""),
        "skills": [s.strip() for s in flags.get("skills", "").split(",") if s.strip()],
        "tools": [t.strip() for t in flags.get("tools", "").split(",") if t.strip()] or ["git-status-diff", "memory-sync"],
        "persona": flags.get("persona", ""),
        "effort": flags.get("effort", "medium"),
        "cid": flags.get("cid", ""),
    }
    ensure_server_running()
    try:
        res = api_post("/api/team/add-agent", payload)
    except Exception as e:
        print(f"[HATA] İstek gönderilemedi: {e}")
        return 1
    if res.get("success"):
        print(f"[OK] Yeni ajan eklendi: #{res['aid']} {res['name']} ({res['target']}) [Runtime: {runtime}]")
        return 0
    print(f"[HATA] {res.get('error')}")
    return 1


def cmd_remove_agent(args):
    if len(args) < 2:
        print("Kullanım: team remove-agent <takım-adı> <@hedef|isim|id>")
        return 1
    ensure_server_running()
    res = api_post("/api/team/remove-agent", {"team": args[0], "target": args[1]})
    print(f"[OK] {res.get('message')}" if res.get("success") else f"[HATA] {res.get('error')}")
    return 0 if res.get("success") else 1


def cmd_dispatch(args):
    if len(args) < 3:
        print("Kullanım: team dispatch <takım> <@hedef> <mesaj>")
        return 1
    ensure_server_running()
    res = api_post("/api/dispatch", {"team": args[0], "target": args[1], "message": " ".join(args[2:]), "sender": os.environ.get("HIVE_AGENT", "CLI")})
    if res.get("success"):
        ids = ", ".join(f"#{i}" for i in res.get("task_ids") or [])
        print(f"[OK] Görev {ids} {args[1]} hedefine iletildi. Bitince sonuç bildirimi gelir; bekleme yapma.")
        return 0
    print(f"[HATA] {res.get('error')}")
    return 1


def cmd_tasks(args):
    if not args:
        print("Kullanım: team tasks <takım> [--all]")
        return 1
    ensure_server_running()
    q = "?all=1" if "--all" in args else ""
    with urllib.request.urlopen(f"{API_URL}/api/team/{args[0]}/ledger{q}") as resp:
        tasks = json.loads(resp.read().decode("utf-8")).get("tasks", [])
    if not tasks:
        print("Açık görev yok." if not q else "Görev yok.")
        return 0
    for t in tasks:
        print(f"#{t['id']:<5} {t['status']:<9} {t['target']:<12} {_fmt_tokens(t['tokens']):>7}  {t['title'][:80]}")
        if t["review_note"]:
            print(f"       ↳ inceleme: {t['review_note'][:100]}")
    return 0


def _fmt_tokens(n: int) -> str:
    return f"{n / 1e6:.1f}M" if n >= 1e6 else (f"{n / 1e3:.0f}k" if n >= 1e3 else str(n))


def cmd_review(args):
    if len(args) < 3 or args[2].lower() not in ("onay", "ret", "approve", "reject"):
        print('Kullanım: team review <takım> <görev-id> onay|ret ["düzeltme notu"]')
        return 1
    ensure_server_running()
    res = api_post("/api/task/review", {
        "team": args[0], "id": args[1].lstrip("#"), "decision": args[2], "note": " ".join(args[3:]),
        "sender": os.environ.get("HIVE_AGENT", "User"),
    })
    if not res.get("success"):
        print(f"[HATA] {res.get('error')}")
        return 1
    extra = ""
    if res.get("retry", {}).get("task_ids"):
        extra = f" Düzeltme görevi #{res['retry']['task_ids'][0]} olarak geri gönderildi."
    print(f"[OK] #{res['id']} → {res['status']}.{extra}")
    return 0


def _cmd_inbox(args, kind):
    if len(args) < 2:
        print(f'Kullanım: team {"ask-user" if kind == "question" else "tell-user"} <takım> "mesaj"')
        return 1
    ensure_server_running()
    res = api_post("/api/inbox", {"team": args[0], "message": " ".join(args[1:]), "kind": kind,
                                  "sender": os.environ.get("HIVE_AGENT", "CLI")})
    if not res.get("success"):
        print(f"[HATA] {res.get('error')}")
        return 1
    tail = " Cevap sana not olarak gelecek; beklemeden turunu bitir." if kind == "question" else ""
    print(f"[OK] Kullanıcıya iletildi (#{res['id']}).{tail}")
    return 0


def cmd_lock(args):
    if len(args) < 2:
        print("Kullanım: team lock <takım> <dosya...>")
        return 1
    res = _engine().lock_files(args[0], os.environ.get("HIVE_AGENT", "User"), args[1:])
    if res["success"]:
        print(f"[OK] {len(res['locked'])} dosya kilitlendi.")
        return 0
    print("[KİLİTLİ] Şu dosyalar başka ajanda, hiçbiri kilitlenmedi:")
    for path, owner in res["conflicts"].items():
        print(f"  {owner:<12} {path}")
    return 1


def cmd_unlock(args):
    if not args:
        print("Kullanım: team unlock <takım> [dosya...]   (dosya verilmezse tüm kilitlerin açılır)")
        return 1
    n = _engine().unlock_files(args[0], os.environ.get("HIVE_AGENT", "User"), args[1:] or None)
    print(f"[OK] {n} kilit açıldı.")
    return 0


def cmd_locks(args):
    if not args:
        print("Kullanım: team locks <takım>")
        return 1
    locks = _engine().list_file_locks(args[0])
    for l in locks:
        print(f"{l['agent']:<12} {l['created_at']}  {l['path']}")
    if not locks:
        print("Aktif kilit yok.")
    return 0


def cmd_deploy(args):
    """team deploy <takım> [--tasks 12,13] [--force] -- <deploy komutu...>"""
    if "--" not in args or args.index("--") < 1:
        print("Kullanım: team deploy <takım> [--tasks 12,13] [--force] -- <deploy komutu>")
        return 1
    sep = args.index("--")
    opts, command = args[:sep], args[sep + 1:]
    flags, rest = _parse_flags(opts[1:], {"--tasks": "tasks"})
    try:
        task_ids = [int(x.strip().lstrip("#")) for x in flags.get("tasks", "").split(",") if x.strip()]
    except ValueError:
        print("[HATA] --tasks virgülle ayrılmış görev numaraları olmalı (ör. --tasks 12,13)")
        return 1
    return _engine().run_deploy(opts[0], command, os.environ.get("HIVE_AGENT", "User"), task_ids, force="--force" in rest)


def cmd_deploys(args):
    if not args:
        print("Kullanım: team deploys <takım>")
        return 1
    for d in _engine().list_deploys(args[0]):
        tasks = f" görevler: {d['task_ids']}" if d["task_ids"] else ""
        print(f"#{d['id']:<4} {d['status']:<8} {d['started_at']}  {d['requested_by']:<6} {d['command'][:70]}{tasks}")
    return 0


def cmd_note(args):
    if len(args) < 3:
        print("Kullanım: team note <takım> <@hedef> <not>")
        return 1
    flags, rest = _parse_flags(args[2:], {"--from": "sender"})
    ensure_server_running()
    res = api_post("/api/note", {"team": args[0], "target": args[1], "note": " ".join(rest), "sender": flags.get("sender", os.environ.get("HIVE_AGENT", "Tech Lead (CLI)"))})
    print(f"[OK] /btw notu {args[1]} hedefine iletildi." if res.get("success") else f"[HATA] {res.get('error')}")
    return 0 if res.get("success") else 1


def _cid_for(conn, team_name, target):
    if target in ("@lead", "lead"):
        t = conn.execute("SELECT lead_cid FROM teams WHERE name=?", (team_name,)).fetchone()
        return t["lead_cid"] if t else ""
    ag = conn.execute("SELECT cid FROM agents WHERE team_name=? AND target=?", (team_name, target)).fetchone()
    return ag["cid"] if ag else ""


def cmd_logs(args):
    if not args:
        print("Kullanım: team logs <takım-adı> [@hedef]")
        return 1
    engine = _engine()
    team_name, target = args[0], (args[1] if len(args) > 1 else "@lead")
    engine.sync_and_migrate()
    with engine.get_db() as conn:
        cid = _cid_for(conn, team_name, target)
    snap = engine.read_brain_snapshot(cid, f"{team_name}:{target}")
    print(f"=== {team_name.upper()} {target} | Durum: {snap['status'].upper()} | Adım: #{snap['telemetry']['steps']} ===")
    if snap["thinking"]:
        print(f"\n[DÜŞÜNCE]\n{snap['thinking']}\n")
    if snap["tool_calls"]:
        print("[ARAÇLAR]\n" + "\n".join(f"• {tc['name']}: {tc['detail']}" for tc in snap["tool_calls"]))
    print(f"\n[MARKDOWN ÇIKTI]\n{snap['markdown']}")
    return 0


def cmd_tools(args):
    sub = args[0] if args else "list"
    if sub == "list":
        eco = _engine().discover_agy_ecosystem()
        print("=" * 90)
        print("ARAÇ VE SKILL MERKEZİ (TOOL & SKILL HUB)")
        print("=" * 90)
        print(f"{'ID':<25} {'TÜR':<14} {'AD':<25} {'AÇIKLAMA'}")
        print("-" * 90)
        for t in eco["tools"]:
            print(f"{t['id']:<25} {t.get('category', 'tool'):<14} {t['name']:<25} {t.get('description', '')[:30]}")
        print("-" * 90)
        print(f"Toplam {len(eco['skills'])} Antigravity Skill ve {len(eco['tools'])} hızlı araç hazır.")
        print("=" * 90)
        return 0
    if sub == "run" and len(args) >= 4:
        ensure_server_running()
        res = api_post("/api/agent/run-tool", {"team": args[1], "target": args[2], "tool_id": args[3]})
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0
    print("Kullanım: team tools [list | run <takım> <hedef> <araç-id>]")
    return 1


def cmd_open(args):
    if not args:
        print("Kullanım: team open <@hedef> [takım-adı]")
        return 1
    engine = _engine()
    target, team_name = args[0], (args[1] if len(args) > 1 else _engine().default_team())
    engine.sync_and_migrate()
    with engine.get_db() as conn:
        if target in ("@lead", "lead"):
            row = conn.execute(
                "SELECT lead_cid as cid, project_dir as workspace_dir, 'Tech Lead' as name, lead_runtime as runtime, '' as model FROM teams WHERE name=?",
                (team_name,),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM agents WHERE team_name=? AND (target=? OR target=?)",
                (team_name, target, f"@{target.lstrip('@')}"),
            ).fetchone()
    if not row:
        print(f"[HATA] Ajan bulunamadı: {target}")
        return 1
    wdir = row["workspace_dir"] or os.getcwd()
    cid = row["cid"] or ""
    runtime = row["runtime"] if "runtime" in row.keys() and row["runtime"] else "agy"
    model = row["model"] if "model" in row.keys() and row["model"] else ""
    print(f"\033[1;32m>>> {row['name']} ({target}) interaktif terminal oturumu başlatılıyor...\033[0m")
    print(f"\033[36mDizin: {wdir} | Motor: {runtime} | CID: {cid or 'yeni'}\033[0m\n")
    if runtime == "claude":
        cmd = ["claude", "--dangerously-skip-permissions"] + (["--resume", cid] if cid else [])
    elif runtime == "codex":
        cmd = ["codex"]
    elif runtime == "aider":
        cmd = ["aider"]
    elif runtime == "ollama":
        cmd = ["ollama", "run", model or "llama3.2"]
    else:
        cmd = ["agy", "--mode", "auto"] + (["-c", cid] if cid else [])
    return subprocess.run(engine.resolve_cli_command(cmd), cwd=wdir).returncode


def cmd_watch(args):
    engine = _engine()
    team_name = args[0] if args else _engine().default_team()
    target = (args[1] if len(args) > 1 else "all").lower().lstrip("@")
    ensure_server_running()
    print(f"\033[1;36m=== HIVEFORGE CANLI AKIŞ: Takım={team_name.upper()}, Hedef=@{target} ===\033[0m")
    print("\033[90m(Çıkmak için Ctrl+C tuşlayın)\033[0m\n")
    last_seen = {}
    try:
        while True:
            with engine.get_db() as conn:
                if target in ("all", "lead"):
                    t = conn.execute("SELECT lead_cid FROM teams WHERE name=?", (team_name,)).fetchone()
                    if t:
                        snap = engine.read_brain_snapshot(t["lead_cid"] or "", f"{team_name}:@lead")
                        sig = f"{snap['status']}|{snap['telemetry']['steps']}|{len(snap['markdown'])}"
                        if last_seen.get("lead") != sig:
                            last_seen["lead"] = sig
                            print(f"\n\033[1;35m--- [TECH LEAD @lead • {snap['status'].upper()} • Adım #{snap['telemetry']['steps']}] ---\033[0m")
                            if snap["thinking"]:
                                print(f"\033[33m🧠 Düşünce: {snap['thinking'][:200]}...\033[0m")
                            print(snap["markdown"][-800:])
                for r in conn.execute("SELECT * FROM agents WHERE team_name=? ORDER BY aid ASC", (team_name,)).fetchall():
                    t_clean = r["target"].lower().lstrip("@")
                    if target in ("all", t_clean, str(r["aid"])):
                        snap = engine.read_brain_snapshot(r["cid"] or "", f"{team_name}:{r['target']}")
                        sig = f"{snap['status']}|{snap['telemetry']['steps']}|{len(snap['markdown'])}"
                        if last_seen.get(r["target"]) != sig:
                            last_seen[r["target"]] = sig
                            color = "\033[32m" if snap["status"] == "idle" else "\033[33m"
                            print(f"\n{color}=== [{r['name']} ({r['target']}) • {snap['status'].upper()} • Adım #{snap['telemetry']['steps']}] ===\033[0m")
                            if snap["tool_calls"]:
                                tools_s = ", ".join(f"{tc['name']}({tc['detail']})" for tc in snap["tool_calls"][-3:])
                                print(f"\033[36m⚡ Araçlar: {tools_s}\033[0m")
                            if snap["thinking"]:
                                print(f"\033[33m🧠 Düşünce: {snap['thinking'][:180]}...\033[0m")
                            print(snap["markdown"][-700:])
            time.sleep(1.2)
    except KeyboardInterrupt:
        print("\n\033[32mİzleme sonlandırıldı.\033[0m")
    return 0


def cmd_ui(args):
    ensure_server_running()
    if os.environ.get("HIVEFORGE_NO_BROWSER") != "1":
        try:
            webbrowser.open(API_URL)
        except Exception:
            pass
    print("=" * 66)
    print(f"🚀 HiveForge Kokpiti Hazır: {API_URL}")
    print("=" * 66)
    if args:
        return cmd_agents(args[:1])
    default = _engine().default_team()
    return cmd_agents([default]) if default else cmd_list([])


def cmd_server(_args):
    os.chdir(ENGINE_DIR)
    return subprocess.run([sys.executable, str(ENGINE_DIR / "server.py"), str(_port())]).returncode


def cmd_tmux(_args):
    # Linux/macOS: `team tmux` is handled by the bin/team wrapper before reaching here.
    print("[BİLGİ] tmux Mission Control yalnızca Linux/macOS'ta `team tmux` ile çalışır. Bunun yerine: hive watch <takım> [hedef]")
    return 1


COMMANDS = {
    **dict.fromkeys(["", "ui", "cockpit", "dashboard", "start", "restart"], cmd_ui),
    **dict.fromkeys(["list", "ls"], cmd_list),
    **dict.fromkeys(["agents", "status"], cmd_agents),
    **dict.fromkeys(["tokens", "token", "usage", "stats"], cmd_tokens),
    "create": cmd_create,
    **dict.fromkeys(["add-agent", "spawn-agent", "new-agent"], cmd_add_agent),
    **dict.fromkeys(["remove-agent", "rm-agent", "kill-agent", "delete-agent"], cmd_remove_agent),
    **dict.fromkeys(["dispatch", "send"], cmd_dispatch),
    **dict.fromkeys(["note", "btw"], cmd_note),
    **dict.fromkeys(["tasks", "task", "ledger"], cmd_tasks),
    "review": cmd_review,
    "deploy": cmd_deploy,
    "deploys": cmd_deploys,
    "lock": cmd_lock,
    "unlock": cmd_unlock,
    "locks": cmd_locks,
    "ask-user": lambda a: _cmd_inbox(a, "question"),
    "tell-user": lambda a: _cmd_inbox(a, "info"),
    **dict.fromkeys(["logs", "log"], cmd_logs),
    **dict.fromkeys(["tools", "tool"], cmd_tools),
    **dict.fromkeys(["open", "jump"], cmd_open),
    **dict.fromkeys(["watch", "tail", "follow", "live"], cmd_watch),
    **dict.fromkeys(["tmux", "attach", "attach-session", "mission-control"], cmd_tmux),
    "server": cmd_server,
    "stop": lambda _a: stop_server(),
    "restore": lambda _a: subprocess.run([sys.executable, str(ENGINE_DIR / "engine.py")]).returncode,
}


def main(argv) -> int:
    try:
        return _main(argv)
    except urllib.error.URLError as e:
        print(f"[HATA] HiveForge sunucusuna ulaşılamadı ({API_URL}): {e.reason}")
        print(f"       Log: {BASE_DIR / 'logs' / 'server.log'}")
        return 1


def _main(argv) -> int:
    cmd = argv[0] if argv else ""
    rest = argv[1:]
    if cmd in ("help", "--help", "-h"):
        print(HELP)
        return 0
    if cmd == "restart":
        stop_server()
    fn = COMMANDS.get(cmd)
    if fn:
        return fn(rest) or 0
    if (TEAMS_DIR / cmd).is_dir():
        return cmd_ui([cmd])
    print(f"[BİLGİ] Bilinmeyen komut veya takım: {cmd}")
    print(HELP)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
