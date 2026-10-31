import os, sys, tempfile
os.environ.setdefault("AGY_TEAMS_DIR", tempfile.mkdtemp())
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
import asyncio, time, types
import engine

engine.init_db()
with engine.get_db() as c:
    c.execute("INSERT INTO teams (name, project_dir, lead_cid) VALUES ('t', '/tmp', 'leadcid')")
    c.execute("INSERT INTO agents (team_name, aid, name, role, target, cid) VALUES ('t', 1, 'A', 'r', '@a', 'acid')")
engine.find_interactive_tmux_pane = lambda **k: None
engine.ROTATE_TOKENS = 0
cum = {"acid": 0}
engine._cum_tokens = lambda team, target, runtime, model, cid: cum.get(cid, 0)
async def fake_turn(team, target, runtime, model, cid, *a):
    cum[cid] = cum.get(cid, 0) + 450
    return True, cid, "ok"
real_turn = engine.execute_headless_agent_turn
engine.execute_headless_agent_turn = fake_turn
alerts = lambda: [i["message"] for i in engine.list_inbox("t") if i["sender"] == "HiveForge"]

async def main():
    assert engine.set_daily_budget("t", 1000) and engine.get_daily_budget("t") == 1000
    for _ in range(2):                                   # 450, 900 -> crosses 80%
        await engine.dispatch_message("t", "@a", "iş")
        await asyncio.sleep(0.2)
    assert engine.tokens_today("t") == {"@a": 900}
    assert len(alerts()) == 1 and "%80" in alerts()[0], alerts()
    await engine.dispatch_message("t", "@a", "iş")       # 1350 -> crosses 100%
    await asyncio.sleep(0.2)
    assert any("%100" in m for m in alerts()), alerts()
    r = await engine.dispatch_message("t", "@a", "iş", sender="@lead")
    assert not r["success"] and "bütçesi doldu" in r["error"], r
    r = await engine.dispatch_message("t", "@a", "iş", sender="User")
    assert r["success"] and "UYARI" in r["output"], r
    await asyncio.sleep(0.2)
    engine.set_daily_budget("t", 0)
    assert (await engine.dispatch_message("t", "@a", "iş", sender="@lead"))["success"], "bütçe kapalıyken engel yok"
    await asyncio.sleep(0.2)

    # runaway guard: a turn whose step counter jumps past HIVE_MAX_STEPS is killed
    engine.execute_headless_agent_turn = real_turn
    engine.MAX_TURN_STEPS, engine.STEP_POLL_SEC = 5, 0.1
    steps = iter([100] + [100 + 10 * i for i in range(1, 100)])
    engine.read_brain_snapshot = lambda cid, **k: {"telemetry": {"steps": next(steps)}}
    engine.shutil.which = lambda b: "/usr/bin/" + b
    real_exec = asyncio.create_subprocess_exec
    async def fake_exec(*cmd, **kw):
        return await real_exec("sleep", "30", **kw)
    engine.asyncio.create_subprocess_exec = fake_exec
    t0 = time.time()
    ok, _, out = await engine.execute_headless_agent_turn("t", "@a", "agy", "", "acid", "/tmp", "", "", "auto", "x")
    assert not ok and "adım sınırını aştı" in out and time.time() - t0 < 5, (ok, out)
    assert any("durduruldu" in m for m in alerts())
    print("OK")
asyncio.run(main())
