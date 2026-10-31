import os, sys, tempfile
os.environ.setdefault("AGY_TEAMS_DIR", tempfile.mkdtemp())
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import asyncio
import engine
engine.init_db()
with engine.get_db() as c:
    c.execute("INSERT INTO teams (name, project_dir) VALUES ('t', '/tmp')")
    for i, t in enumerate(("@a", "@b", "@c"), 1):
        c.execute("INSERT INTO agents (team_name, aid, name, role, target, cid) VALUES ('t', ?, ?, 'r', ?, 'x')", (i, t, t))
engine.find_interactive_tmux_pane = lambda **k: None
engine.ROTATE_TOKENS = 0
calls = []
async def fake_turn(team, target, runtime, model, cid, wdir, persona, effort, mode, prompt, is_lead, hops=0):
    calls.append((target, prompt, hops))
    await asyncio.sleep(0.3 if target == "@b" else 0.05)
    if target == "@a" and "soru" in prompt:
        return True, cid, "/btw @c cevabın ne?"     # question, hop 1
    if target == "@c" and "cevabın" in prompt:
        return True, cid, "/btw @a cevap: 42"       # answer, hop 2
    if target == "@a" and "cevap: 42" in prompt:
        return True, cid, "/btw @c teşekkürler"     # hop 3: must be dropped
    return True, cid, f"{target} ok"
engine.execute_headless_agent_turn = fake_turn

async def main():
    await engine.dispatch_message("t", "@a", "soru sor", sender="@lead")
    await engine.dispatch_message("t", "@b", "iş", sender="@lead")
    await asyncio.sleep(0.15)
    st = engine.batch_status("t")
    assert st["batch"] == 1 and st["agents"].get("@b") == "running" and "@c" not in st["agents"], st
    await asyncio.sleep(1.0)
    lead = [p for who, p, h in calls if who == "@lead"]
    assert len(lead) == 1 and "[GÖREVLER BİTTİ • parti 1] 2/2 tamam." in lead[0], lead  # one report, not one per task
    assert engine.batch_status("t")["agents"] == {"@a": "done", "@b": "done"}
    assert not [1 for who, p, h in calls if who == "@c" and "teşekkürler" in p], "cevaba cevap iletilmemeli"
    assert [h for who, p, h in calls if who == "@a" and "cevap: 42" in p] == [2]
    # CLI-originated note from a hop-2 turn is refused too
    r = await engine.dispatch_message("t", "@c", "x", sender="@a", msg_type="note", hops=3)
    assert not r["success"]
    # next lead dispatch opens a new batch
    await engine.dispatch_message("t", "@c", "yeni", sender="@lead")
    assert engine.batch_status("t")["batch"] == 2
    await asyncio.sleep(0.3)
    print("OK")
asyncio.run(main())
