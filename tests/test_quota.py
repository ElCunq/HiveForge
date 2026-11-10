import os, sys, tempfile
os.environ.setdefault("AGY_TEAMS_DIR", tempfile.mkdtemp())
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import asyncio
import engine
engine.init_db()
with engine.get_db() as c:
    c.execute("INSERT INTO teams (name, project_dir) VALUES ('t', '/tmp')")
    for i, t in enumerate(("@a", "@b"), 1):
        c.execute("INSERT INTO agents (team_name, aid, name, role, target, cid) VALUES ('t', ?, ?, 'r', ?, 'x')", (i, t, t))
engine.find_interactive_tmux_pane = lambda **k: None
engine.ROTATE_TOKENS = 0
quota_on, calls = [True], []
async def fake_turn(team, target, runtime, model, cid, wdir, persona, effort, mode, prompt, is_lead, hops=0):
    calls.append((target, prompt))
    await asyncio.sleep(0.05)
    if target == "@a" and quota_on[0]:
        return False, cid, "You've hit your 5-hour limit · resets 9pm (Europe/Istanbul)"
    return True, cid, f"{target} ok"
engine.execute_headless_agent_turn = fake_turn

async def main():
    for line in ("error: Individual quota reached. Resets in 2h", "RESOURCE_EXHAUSTED", "You've hit your 5-hour limit"):
        assert engine.QUOTA_RE.search(line), line
    assert not engine.QUOTA_RE.search("Hata: cargo build failed")

    await engine.dispatch_message("t", "@a", "giriş sayfası", sender="@lead")
    await engine.dispatch_message("t", "@b", "api", sender="@lead")
    await asyncio.sleep(0.5)
    st = engine.batch_status("t")
    assert st["quota"] == ["@a"] and st["agents"] == {"@a": "quota", "@b": "done"}, st
    assert not [1 for who, _ in calls if who == "@lead"], "kota bekleyen görev varken lead'e 'bitti' raporu gitmemeli"
    with engine.get_db() as c:
        assert c.execute("SELECT 1 FROM inbox WHERE message LIKE 'Model kotası doldu%'").fetchone()

    quota_on[0] = False
    res = await engine.resume_quota("t")
    assert res["resumed"] == ["@a"], res
    await asyncio.sleep(0.5)
    resume_prompt = [p for who, p in calls if who == "@a"][-1]
    assert "Kota yenilendi, devam et" in resume_prompt and "giriş sayfası" in resume_prompt, resume_prompt
    st = engine.batch_status("t")
    assert st["quota"] == [] and st["batch"] == 1 and st["agents"] == {"@a": "done", "@b": "done"}, st
    lead = [p for who, p in calls if who == "@lead"]
    assert len(lead) == 1 and "[GÖREVLER BİTTİ • parti 1] 2/2 tamam." in lead[0] and "resumed" not in lead[0], lead
    assert (await engine.resume_quota("t"))["resumed"] == []
    print("OK")
asyncio.run(main())
