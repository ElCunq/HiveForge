import os, sys, tempfile
os.environ.setdefault("AGY_TEAMS_DIR", tempfile.mkdtemp())
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "bin"))
import asyncio, io, contextlib
import engine, server, hive
from aiohttp.test_utils import TestClient, TestServer

engine.init_db()
with engine.get_db() as c:
    c.execute("INSERT INTO teams (name, project_dir, lead_cid) VALUES ('t', '/tmp', 'leadcid')")
engine.find_interactive_tmux_pane = lambda **k: None
engine.ROTATE_TOKENS = 0
calls = []
async def fake_turn(team, target, runtime, model, cid, wdir, persona, effort, mode, prompt, is_lead):
    calls.append((target, prompt)); return True, cid, "ok"
engine.execute_headless_agent_turn = fake_turn

async def main():
    async with TestClient(TestServer(server.create_app(), host="127.0.0.1")) as cl:
        h = {"Origin": f"http://127.0.0.1:{cl.port}"}
        post = lambda path, body: cl.post(path, json=body, headers=h)
        q = await (await post("/api/inbox", {"team": "t", "sender": "@lead", "kind": "question", "message": "Deploy edeyim mi?"})).json()
        i = await (await post("/api/inbox", {"team": "t", "sender": "@lead", "message": "Sprint bitti"})).json()
        items = (await (await cl.get("/api/team/t/inbox")).json())["items"]
        assert {x["id"]: x["kind"] for x in items} == {q["id"]: "question", i["id"]: "info"}, items
        assert (await post("/api/inbox/answer", {"team": "t", "id": q["id"], "answer": ""})).status == 400
        r = await post("/api/inbox/answer", {"team": "t", "id": q["id"], "answer": "Evet, önce api"})
        assert r.status == 200
        await asyncio.sleep(0.3)
        lead = [p for who, p in calls if who == "@lead"]
        assert lead and f"[KULLANICI CEVABI #{q['id']}]" in lead[0] and "Evet, önce api" in lead[0] and "Deploy edeyim mi?" in lead[0], lead
        assert (await post("/api/inbox/answer", {"team": "t", "id": q["id"], "answer": "tekrar"})).status == 400
        assert (await post("/api/inbox/answer", {"team": "t", "id": i["id"]})).status == 200
        st = {x["id"]: x["status"] for x in (await (await cl.get("/api/team/t/inbox")).json())["items"]}
        assert st == {q["id"]: "answered", i["id"]: "read"}, st

    # deploy result lands in the inbox
    with contextlib.redirect_stdout(io.StringIO()):
        engine.run_deploy("t", ["false"], "@lead", [])
    top = engine.list_inbox("t")[0]
    assert top["status"] == "open" and "BAŞARISIZ" in top["message"], top

    # CLI sends as the calling agent
    sent = {}
    hive.ensure_server_running = lambda: None
    hive.api_post = lambda path, p: sent.update(p, _path=path) or {"success": True, "id": 9}
    os.environ["HIVE_AGENT"] = "@lead"
    with contextlib.redirect_stdout(io.StringIO()):
        hive.COMMANDS["ask-user"](["t", "Onay", "lazım"])
    assert sent == {"team": "t", "message": "Onay lazım", "kind": "question", "sender": "@lead", "_path": "/api/inbox"}, sent
    print("OK")
asyncio.run(main())
