import os, sys, tempfile
os.environ.setdefault("AGY_TEAMS_DIR", tempfile.mkdtemp())
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import asyncio
os.environ["AGY_TEAMS_DIR"] = tempfile.mkdtemp(); os.environ["HIVE_TURN_TIMEOUT"] = "0.5"
import engine, time
engine.init_db()
with engine.get_db() as c:
    c.execute("INSERT INTO teams (name, project_dir) VALUES ('t', '/tmp')")
    c.execute("INSERT INTO agents (team_name, aid, name, role, target, runtime) VALUES ('t', 1, 'A', 'r', '@a', 'sleep 30;')")
t = time.time()
ok, _, out = asyncio.run(engine.execute_headless_agent_turn("t", "@a", "sleep 30;", "", "", "/tmp", "", "", "auto", "x"))
assert not ok and "bitmedi" in out and time.time() - t < 5, (ok, out)
print("OK", round(time.time() - t, 1), "sn")
