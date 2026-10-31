import os, sys, tempfile
os.environ.setdefault("AGY_TEAMS_DIR", tempfile.mkdtemp())
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import asyncio
import engine

engine.init_db()
with engine.get_db() as c:
    c.execute("INSERT INTO teams (name, project_dir) VALUES ('anikuro', '/tmp')")
    c.execute("INSERT INTO agents (team_name, aid, name, role, target) VALUES ('anikuro', 1, 'S', 'r', '@server')")

calls = []
async def fake_dispatch(team, to, msg, sender, msg_type, hops):
    calls.append((to, msg, sender, hops)); return {"success": True}
engine.dispatch_message = fake_dispatch

out = "Bitti.\n/btw @lead Testler yeşil, deploy hazır.\n  /btw @web: endpoint değişti\n/btw @server kendime not\nmetin /btw @x satır içi değil"
n = asyncio.run(engine.route_btw_notes("t", "@server", out, 1))
assert n == 2, calls
assert calls[0] == ("@lead", "Testler yeşil, deploy hazır.", "@server", 1)
assert calls[1][:2] == ("@web", "endpoint değişti")

p = engine.build_agent_orchestration_prompt("anikuro", "@lead", "x")
assert "KENDİN YAPMA" in p and "team dispatch anikuro" in p and "Deploy SENİN" in p, p
assert "LİDER" not in engine.build_agent_orchestration_prompt("anikuro", "@server", "x")
print("OK")
