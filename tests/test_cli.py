import os, sys, tempfile, types
os.environ.setdefault("AGY_TEAMS_DIR", tempfile.mkdtemp())
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "bin"))
import engine, hive

# note --from and agent identity from HIVE_AGENT
sent = {}
hive.ensure_server_running = lambda: None
hive.api_post = lambda path, p: sent.update(p, _path=path) or {"success": True}
hive.cmd_note(["t", "@fansub", "--from", "lead", "raporu", "yaz"])
assert sent["sender"] == "lead" and sent["note"] == "raporu yaz", sent
os.environ.pop("HIVE_AGENT", None)
hive.cmd_note(["t", "@fansub", "merhaba"]); assert sent["sender"] == "Tech Lead (CLI)"
os.environ["HIVE_AGENT"] = "@lead"
hive.cmd_dispatch(["t", "@a", "iş"]); assert sent["sender"] == "@lead"
hive.cmd_note(["t", "@a", "not"]); assert sent["sender"] == "@lead"

# tmux: whole-tag pane title match
out = "%1|111|@webhook worker\n%2|222|Ajan @web (frontend)\n%3|333|@web.old"
engine.subprocess.run = lambda *a, **k: types.SimpleNamespace(returncode=0, stdout=out)
engine.shutil.which = lambda b: "/usr/bin/tmux"
assert engine.find_interactive_tmux_pane(target="@web") == "%2"
assert engine.find_interactive_tmux_pane(target="@webhook") == "%1"
assert engine.find_interactive_tmux_pane(target="@we") is None
print("OK")
