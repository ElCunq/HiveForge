import os, sys, tempfile
os.environ.setdefault("AGY_TEAMS_DIR", tempfile.mkdtemp())
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import asyncio
import engine
engine.init_db()
with engine.get_db() as c:
    c.execute("INSERT INTO teams (name, project_dir) VALUES ('t', '/tmp')")
    c.execute("INSERT INTO agents (team_name, aid, name, role, target, runtime) VALUES ('t', 1, 'A', 'r', '@a', 'claude')")
cmds = []
class P:
    pid, returncode = 1, 0
    async def communicate(self): return b"tamam", b""
async def fake_exec(*cmd, **kw): cmds.append(cmd); return P()
engine.asyncio.create_subprocess_exec = fake_exec
engine.shutil.which = lambda b: "/usr/bin/" + b
def cid():
    with engine.get_db() as c: return c.execute("SELECT cid FROM agents WHERE target='@a'").fetchone()[0]
async def main():
    await engine.execute_headless_agent_turn("t", "@a", "claude", "", "", "/tmp", "", "low", "auto", "bir")
    sid = cid(); assert sid and "--session-id" in cmds[0] and sid in cmds[0], cmds[0]
    await engine.execute_headless_agent_turn("t", "@a", "claude", "", sid, "/tmp", "", "low", "auto", "iki")
    assert cmds[1][cmds[1].index("--resume") + 1] == sid and "--session-id" not in cmds[1]
    print("OK", sid)
asyncio.run(main())
