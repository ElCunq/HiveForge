import os, sys, tempfile
os.environ.setdefault("AGY_TEAMS_DIR", tempfile.mkdtemp())
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import asyncio
PROJ = tempfile.mkdtemp()
import engine
engine.init_db()
with engine.get_db() as c:
    c.execute("INSERT INTO teams (name, project_dir, lead_cid) VALUES ('t', ?, 'leadcid')", (PROJ,))
    c.execute("INSERT INTO agents (team_name, aid, name, role, target, cid) VALUES ('t', 1, 'A', 'r', '@a', 'bigcid')")
engine.find_interactive_tmux_pane = lambda **k: None
CTX = {"bigcid": 150_000, "leadcid": 50_000}
engine.read_brain_snapshot = lambda cid, **k: {"telemetry": {"context_tokens": CTX.get(cid, 0)}}
calls, handoff_ok = [], [True]
async def fake_turn(team, target, runtime, model, cid, wdir, persona, effort, mode, prompt, is_lead):
    calls.append((target, cid, prompt))
    if "OTURUM DEVRİ" in prompt:
        return handoff_ok[0], cid, "DEVİR TAMAM"
    return True, cid, f"{target} işi bitirdi"
engine.execute_headless_agent_turn = fake_turn
def db_cid(t):
    with engine.get_db() as c: return c.execute("SELECT cid FROM agents WHERE target=?", (t,)).fetchone()[0]

async def main():
    # 1) big context -> handoff on old session, then task runs in a fresh session; lead gets the result back
    await engine.dispatch_message("t", "@a", "endpoint ekle", sender="@lead")
    await asyncio.sleep(0.5)
    a_calls = [c for c in calls if c[0] == "@a"]
    assert "OTURUM DEVRİ" in a_calls[0][2] and a_calls[0][1] == "bigcid", a_calls[0]
    assert str(engine.agent_memory_file("t", "@a")) in a_calls[0][2]
    assert a_calls[1][1] == "" and a_calls[1][2] == "endpoint ekle", a_calls[1]
    assert db_cid("@a") == ""
    lead_calls = [c for c in calls if c[0] == "@lead"]
    assert lead_calls and "[GÖREV SONUCU — @a • TAMAMLANDI]" in lead_calls[0][2] and "@a işi bitirdi" in lead_calls[0][2], lead_calls
    assert lead_calls[0][1] == "leadcid", "50k lead rotate edilmemeli"
    assert len([c for c in calls if c[0] == "@lead"]) == 1, "sonuç bildirimi geri bildirim döngüsü yaratmamalı"
    # 2) failed handoff keeps the old session
    calls.clear(); handoff_ok[0] = False
    with engine.get_db() as c: c.execute("UPDATE agents SET cid='bigcid' WHERE target='@a'")
    await engine.dispatch_message("t", "@a", "ikinci iş")  # sender User: no callback
    await asyncio.sleep(0.5)
    assert [c[1] for c in calls] == ["bigcid", "bigcid"] and db_cid("@a") == "bigcid", calls
    assert not [c for c in calls if c[0] == "@lead"]
    # 3) prompts: full rules on first turn, short reminder later, lead rule in both
    full = engine.build_agent_orchestration_prompt("t", "@a", "X", first_turn=True)
    short = engine.build_agent_orchestration_prompt("t", "@a", "X", first_turn=False)
    lfull = engine.build_agent_orchestration_prompt("t", "@lead", "X", first_turn=True)
    lshort = engine.build_agent_orchestration_prompt("t", "@lead", "X", first_turn=False)
    assert "TOKEN KURALLARI" in full and "TOKEN KURALLARI" not in short and "LİDER" not in full
    assert "KENDİN YAPMA" in lfull and "KENDİN YAPMA" in lshort
    assert len(short) < 250 and len(lshort) < 500, (len(short), len(lshort))
    for p in (full, short, lfull, lshort):
        assert engine.clean_user_prompt(p) == "X", engine.clean_user_prompt(p)
    print(f"OK (tam blok {len(full)} karakter, hatırlatma {len(short)} / lead {len(lshort)})")
asyncio.run(main())
