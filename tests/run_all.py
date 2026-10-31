"""Runs every tests/test_*.py in its own process with a fresh, throwaway HiveForge data dir."""
import os, sys, subprocess, tempfile
from pathlib import Path

failed = []
for t in sorted(Path(__file__).parent.glob("test_*.py")):
    env = {**os.environ, "AGY_TEAMS_DIR": tempfile.mkdtemp(prefix="hive-test-")}
    env.pop("HIVE_AGENT", None)
    r = subprocess.run([sys.executable, str(t)], env=env, capture_output=True, text=True, timeout=120)
    ok = r.returncode == 0
    print(f"{'PASS' if ok else 'FAIL'}  {t.name}")
    if not ok:
        failed.append(t.name)
        print((r.stdout + r.stderr)[-2000:])
print(f"\n{len(failed)} başarısız" if failed else "\nhepsi geçti")
sys.exit(1 if failed else 0)
