import os, sys, tempfile
os.environ.setdefault("AGY_TEAMS_DIR", tempfile.mkdtemp())
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import sqlite3
import engine
engine.init_db()
fds = lambda: len(os.listdir("/proc/self/fd"))
before = fds()
for _ in range(200):
    with engine.get_db() as c:
        c.execute("SELECT 1").fetchone()
assert fds() <= before + 2, (before, fds())
try:
    c.execute("SELECT 1"); raise SystemExit("bağlantı kapanmamış")
except sqlite3.ProgrammingError:
    pass
try:
    with engine.get_db() as c:
        c.execute("INSERT INTO teams (name, project_dir) VALUES ('x', '/tmp')"); raise RuntimeError
except RuntimeError:
    pass
with engine.get_db() as c:
    assert not c.execute("SELECT 1 FROM teams WHERE name='x'").fetchone(), "hata durumunda rollback olmalı"
print("OK")
