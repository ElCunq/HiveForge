import os, sys, tempfile
os.environ.setdefault("AGY_TEAMS_DIR", tempfile.mkdtemp())
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import asyncio
import engine
engine.init_db()
with engine.get_db() as c:
    c.execute("INSERT INTO teams (name, project_dir) VALUES ('t', '/tmp')")
    c.execute("INSERT INTO agents (team_name, aid, name, role, target, cid) VALUES ('t', 1, 'A', 'r', '@a', 'x')")
engine.find_interactive_tmux_pane = lambda **k: None
from collections import Counter
running, peaks = Counter(), Counter()
async def fake_turn(team, target, *a):
    running[target] += 1; peaks[target] = max(peaks[target], running[target])
    await asyncio.sleep(0.1); running[target] -= 1
    return (a[-2] != "boom"), "x", "çıktı\n/btw @lead bitti"
engine.execute_headless_agent_turn = fake_turn
async def main():
    for m in ("bir", "iki", "boom"):
        await engine.dispatch_message("t", "@a", m)
    await asyncio.sleep(1.5)
asyncio.run(main())
with engine.get_db() as c:
    rows = c.execute("SELECT target, msg_type, status, sender FROM dispatch_queue ORDER BY id").fetchall()
st = [tuple(r) for r in rows]
print(st, dict(peaks))
assert max(peaks.values()) == 1, "aynı ajanda eşzamanlı tur olmamalı"
assert [r[2] for r in st if r[0] == "@a"] == ["done", "done", "error"]
assert ("@lead", "note", "done", "@a") in st, "/btw notu lead'e ulaşmalı"
print("OK")
