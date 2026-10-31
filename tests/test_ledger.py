import os, sys, tempfile
os.environ.setdefault("AGY_TEAMS_DIR", tempfile.mkdtemp())
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import asyncio
import engine, server
from aiohttp.test_utils import TestClient, TestServer

engine.init_db()
with engine.get_db() as c:
    c.execute("INSERT INTO teams (name, project_dir, lead_cid) VALUES ('t', '/tmp', 'leadcid')")
    c.execute("INSERT INTO agents (team_name, aid, name, role, target, cid) VALUES ('t', 1, 'A', 'r', '@a', 'acid')")
engine.find_interactive_tmux_pane = lambda **k: None
engine.ROTATE_TOKENS = 0
spent = {"acid": 1000, "leadcid": 0}
engine._cum_tokens = lambda team, target, runtime, model, cid: spent.get(cid, 0)
calls = []
async def fake_turn(team, target, runtime, model, cid, wdir, persona, effort, mode, prompt, is_lead):
    calls.append((target, prompt))
    spent[cid] = spent.get(cid, 0) + (4200 if target == "@a" else 10)
    return True, cid, f"{target} bitti"
engine.execute_headless_agent_turn = fake_turn

async def main():
    r = await engine.dispatch_message("t", "@a", "## Görev: Arama sayfasını düzelt\ndetaylar...", sender="@lead")
    tid = r["task_ids"][0]
    await asyncio.sleep(0.4)
    [t] = [x for x in engine.list_tasks("t") if x["id"] == tid]
    assert t["status"] == "done" and t["tokens"] == 4200 and t["title"] == "Görev: Arama sayfasını düzelt", t
    lead_prompt = [p for who, p in calls if who == "@lead"][0]
    assert f"[GÖREV SONUCU #{tid} — @a • TAMAMLANDI]" in lead_prompt and f"team review t {tid} onay" in lead_prompt

    # reject with note -> status rejected + fix task goes back to @a, its result comes back to the reviewer
    calls.clear()
    res = await engine.review_task("t", tid, approve=False, note="mobilde taşıyor", reviewer="@lead")
    assert res["success"] and res["status"] == "rejected" and res["retry"]["task_ids"], res
    retry_id = res["retry"]["task_ids"][0]
    await asyncio.sleep(0.4)
    a_prompt = [p for who, p in calls if who == "@a"][0]
    assert f"[#{tid} REDDEDİLDİ — düzelt] mobilde taşıyor" in a_prompt and "Arama sayfasını düzelt" in a_prompt
    assert any(f"#{retry_id}" in p for who, p in calls if who == "@lead")

    # approve via the HTTP API; a second verdict is refused
    async with TestClient(TestServer(server.create_app(), host="127.0.0.1")) as cl:
        h = {"Origin": f"http://127.0.0.1:{cl.port}"}
        r1 = await cl.post("/api/task/review", json={"team": "t", "id": retry_id, "decision": "approve"}, headers=h)
        assert r1.status == 200 and (await r1.json())["status"] == "approved"
        r2 = await cl.post("/api/task/review", json={"team": "t", "id": retry_id, "decision": "approve"}, headers=h)
        assert r2.status == 400
        open_ids = [x["id"] for x in (await (await cl.get("/api/team/t/ledger")).json())["tasks"]]
        all_ids = [x["id"] for x in (await (await cl.get("/api/team/t/ledger?all=1")).json())["tasks"]]
    assert retry_id not in open_ids and tid in open_ids and retry_id in all_ids, (open_ids, all_ids)
    print("OK")
asyncio.run(main())
