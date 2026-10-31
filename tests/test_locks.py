import os, sys, tempfile
os.environ.setdefault("AGY_TEAMS_DIR", tempfile.mkdtemp())
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
import asyncio
import engine, server

engine.init_db()
proj = tempfile.mkdtemp()
with engine.get_db() as c:
    c.execute("INSERT INTO teams (name, project_dir) VALUES ('t', ?)", (proj,))
    c.execute("INSERT INTO agents (team_name, aid, name, role, target) VALUES ('t', 1, 'A', 'r', '@a')")
f1, f2 = os.path.join(proj, "a.rs"), os.path.join(proj, "b.rs")

# relative and absolute spellings are the same lock; locking is all-or-nothing
os.chdir(proj)
assert engine.lock_files("t", "@a", ["a.rs", "./a.rs"])["locked"] == [f1]
r = engine.lock_files("t", "@b", [f2, f1])
assert not r["success"] and r["conflicts"] == {f1: "@a"} and r["locked"] == []
assert [l["path"] for l in engine.list_file_locks("t")] == [f1], "b.rs çakışmada kilitlenmemeli"
assert engine.lock_files("t", "@a", [f1])["success"], "kendi kilidini tekrar almak sorun olmamalı"
assert engine.unlock_files("t", "@b", [f1]) == 0, "başkasının kilidi açılamaz"
assert any(l["scope"] == "hiveforge" and l["agent"] == "@a" for l in server.scan_team_locks("t", proj))

# a finished task releases its agent's locks
engine.find_interactive_tmux_pane = lambda **k: None
engine.ROTATE_TOKENS = 0
engine._cum_tokens = lambda *a: 0
async def fake_turn(*a):
    assert engine.list_file_locks("t"), "tur sürerken kilit durmalı"
    return True, "", "ok"
engine.execute_headless_agent_turn = fake_turn
async def main():
    await engine.dispatch_message("t", "@a", "iş")
    await asyncio.sleep(0.3)
asyncio.run(main())
assert engine.list_file_locks("t") == [], engine.list_file_locks("t")
print("OK")
