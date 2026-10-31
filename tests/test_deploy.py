import os, sys, tempfile
os.environ.setdefault("AGY_TEAMS_DIR", tempfile.mkdtemp())
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
import subprocess, threading, io, contextlib
import engine

engine.init_db()
with engine.get_db() as c:
    c.execute("INSERT INTO teams (name, project_dir) VALUES ('t', '/tmp')")
    for i, st in ((1, "approved"), (2, "done")):
        c.execute("INSERT INTO dispatch_queue (id, team_name, target, msg_type, message, status) VALUES (?, 't', '@a', 'dispatch', 'x', ?)", (i, st))
def quiet(f, *a, **k):
    with contextlib.redirect_stdout(io.StringIO()):
        return f(*a, **k)

# 1) caprover shim: blocks agents, lets lead through only via team deploy, transparent for the user
fake_bin = tempfile.mkdtemp()
with open(os.path.join(fake_bin, "caprover"), "w") as f:
    f.write("#!/usr/bin/env bash\necho REAL \"$@\"\n")
os.chmod(os.path.join(fake_bin, "caprover"), 0o755)
def run_caprover(**env):
    e = {k: v for k, v in os.environ.items() if not k.startswith("HIVE_")}
    e.update(PATH=f"{engine.SHIMS_DIR}:{fake_bin}:/usr/bin:/bin", **env)
    return subprocess.run(["caprover", "deploy", "-a", "api"], env=e, capture_output=True, text=True)
r = run_caprover(HIVE_AGENT="@web"); assert r.returncode == 126 and "sadece Tech Lead" in r.stderr, r
r = run_caprover(HIVE_AGENT="@lead", HIVE_TEAM="t"); assert r.returncode == 126 and "team deploy t" in r.stderr, r
r = run_caprover(HIVE_AGENT="@lead", HIVE_DEPLOY="1"); assert r.returncode == 0 and r.stdout.strip() == "REAL deploy -a api", r
r = run_caprover(); assert r.returncode == 0 and r.stdout.startswith("REAL"), r
assert engine._agent_env("t", "@a")["PATH"].startswith(str(engine.SHIMS_DIR))

# 2) authorization + approval checks
assert quiet(engine.run_deploy, "t", ["true"], "@web", []) == 126
assert quiet(engine.run_deploy, "t", ["true"], "@lead", [1, 2]) == 1, "onaysız #2 reddedilmeli"
assert quiet(engine.run_deploy, "t", ["false"], "@lead", [1]) == 1
with engine.get_db() as c:
    assert c.execute("SELECT status FROM dispatch_queue WHERE id=1").fetchone()[0] == "approved", "başarısız deploy işaretlememeli"
assert quiet(engine.run_deploy, "t", ["bash", "-c", "echo deploying"], "@lead", [1]) == 0
with engine.get_db() as c:
    assert c.execute("SELECT status FROM dispatch_queue WHERE id=1").fetchone()[0] == "deployed"
hist = engine.list_deploys("t")
assert [d["status"] for d in hist[:2]] == ["success", "failed"] and "deploying" in hist[0]["output_tail"], hist

# 3) two deploys at once never overlap
log = os.path.join(tempfile.mkdtemp(), "order")
cmd = ["bash", "-c", f"echo S >> {log}; sleep 0.4; echo E >> {log}"]
ts = [threading.Thread(target=engine.run_deploy, args=("t", cmd, "@lead", [])) for _ in range(2)]
[t.start() for t in ts]; [t.join() for t in ts]
assert open(log).read().split() == ["S", "E", "S", "E"], open(log).read()
print("OK")
