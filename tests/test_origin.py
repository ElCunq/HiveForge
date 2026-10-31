import os, sys, tempfile
os.environ.setdefault("AGY_TEAMS_DIR", tempfile.mkdtemp())
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import asyncio
import server
from aiohttp.test_utils import TestClient, TestServer
async def main():
    async with TestClient(TestServer(server.create_app(), host="127.0.0.1")) as c:
        h = f"127.0.0.1:{c.port}"
        r = await c.get("/api/teams"); assert r.status == 200, r.status                                  # CLI, no Origin
        r = await c.get("/api/teams", headers={"Origin": f"http://{h}"}); assert r.status == 200          # own UI
        r = await c.post("/api/dispatch", data='{}', headers={"Origin": "https://evil.com", "Content-Type": "text/plain"}); assert r.status == 403
        r = await c.get("/api/teams", headers={"Host": "evil.com:4444"}); assert r.status == 403          # DNS rebinding
        r = await c.get("/ws?team=x", headers={"Origin": "https://evil.com"}); assert r.status == 403
    print("OK")
asyncio.run(main())
