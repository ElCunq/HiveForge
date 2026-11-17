<p align="center">
  <img src="static/logo.svg" alt="HiveForge" width="360">
</p>

# HiveForge

HiveForge runs a team of AI coding agents (`agy`, `claude`, `codex`, `aider`, `ollama`, or your own script) on one
codebase. A lead agent hands out tasks, workers report back, and you watch and steer it all from a local web UI or
the terminal.

It exists because running several agent CLIs on the same repo by hand breaks down fast. Agents don't know about each
other, they edit the same files, they poll each other for status and burn tokens, and you lose track of who is doing
what.

<!-- TODO: 30-second demo GIF: docs/demo.gif -->

## What it does

- **Task dispatch with callbacks.** The lead runs `team dispatch <team> @agent "task"`. When the task finishes, the
  result comes back to whoever dispatched it as a note, so nobody has to poll.
- **Agent-to-agent notes.** An agent can write `/btw @other message` in its reply and HiveForge delivers it. Conversation
  depth is capped so two agents can't keep pinging each other forever.
- **File locks.** `team lock` claims files for the length of a task. Conflicting claims are rejected, and locks are
  released when the task turn ends.
- **Task ledger and review.** Each dispatched task is recorded with its owner, status and token cost. A rejected task
  goes back to the agent as a new task, with your note attached.
- **Deploy gate.** Inside agent processes, deploy tools (currently `caprover`) are shimmed. They only run through
  `team deploy`, which is lead-only and allows one deploy at a time.
- **Inbox.** Agents can ask you a question (`team ask-user`) or tell you something (`team tell-user`). Your answer is sent
  back to the agent that asked.
- **Token accounting.** Shows per-agent spend, context usage and cache-hit rate, and enforces an optional daily
  per-agent budget. When an agent's context gets too big, it writes a handoff memory to `.hive/memory/<agent>.md` and
  continues in a fresh session.
- **Quota handling.** An agent that hits a provider quota is marked as quota-stopped instead of failed, and can be
  resumed from the UI.

Agents learn about the team from a context prefix added to each turn and from a generated `TEAM_ORCHESTRATION.md` in
the project. HiveForge never touches your own `AGENTS.md`.

## Runtimes

| Runtime | How it's run | Telemetry |
| --- | --- | --- |
| `agy` (Google Antigravity) | headless or interactive | full step log from its brain JSONL |
| `claude` (Claude Code) | `-p` with `--resume` | turns and tokens stored in SQLite |
| `codex` | `codex exec` | turns stored in SQLite |
| `aider` | `aider --message` | turns stored in SQLite |
| `ollama` | `ollama run <model>` | turns stored in SQLite |
| custom | any shell command | turns stored in SQLite |

Agents with different runtimes can be mixed in one team.

## How it's built

```
bin/hive.py   CLI (hive / team): talks to the server over HTTP
server.py     aiohttp server on 127.0.0.1:4444: REST API + WebSocket snapshots for the UI
engine.py     state (SQLite), runtime adapters, prompt building, dispatch queue, token accounting, deploy gate
static/       web UI (plain JS, no build step)
```

State lives in `~/.agy-teams/` (SQLite plus logs). The server only binds to localhost and rejects cross-origin
requests. The only Python dependency is `aiohttp`.

## Install

Linux / macOS:

```bash
git clone https://github.com/ElCunq/HiveForge.git
cd HiveForge
./install.sh
```

The installer links `hive` and `team` into `~/.local/bin`. It also sets up a `systemd` user service on Linux, or a
`launchd` agent on macOS.

Windows (needs Git for Windows and Python 3.9+, no WSL):

```bat
git clone https://github.com/ElCunq/HiveForge.git
cd HiveForge
hiveforge.bat
```

The first run creates a `.venv`, adds HiveForge to your user `PATH` and opens the UI. After that, `hiveforge <command>`
takes the same commands as `hive`. `tmux` mode isn't available on Windows; use `hiveforge watch` instead.

Uninstall with `./uninstall.sh` or `hiveforge uninstall`. Add `--purge` to also delete saved state.

## Usage

```bash
hive                                   # start the server and open the UI
hive agents <team>                     # agents, runtimes, status, context usage
hive tokens <team>                     # token spend per agent, cache hit rate
hive watch <team> [@agent]             # stream an agent's steps in the terminal
hive open @agent                       # take over an agent in its own interactive CLI
hive tmux <team>                       # one tmux window per agent (Linux/macOS)

team dispatch <team> @backend "Add JWT rotation to the auth middleware"
team note <team> @backend "use Argon2id for password hashes"

team tasks <team>                      # open tasks: status, owner, token cost
team review <team> 42 onay             # approve
team review <team> 42 ret "fix the mobile layout"   # reject, sent back as a new task
team deploy <team> --tasks 42,43 -- caprover deploy -a my-api
team deploys <team>

team lock <team> src/api/stream.rs
team locks <team>
team budget <team> 20M                 # daily per-agent token limit, 0 = off
team ask-user <team> "Deploy api + web now?"
team tell-user <team> "Sprint 19 done"
```

`hive help` prints the full list.

### Settings

| Env var | Default | Meaning |
| --- | --- | --- |
| `HIVE_ROTATE_TOKENS` | `100000` | Context size that triggers a handoff memory and a fresh session (0 = off) |
| `HIVE_MAX_STEPS` | `600` | Stop an `agy` turn after this many steps (0 = off) |
| `HIVE_TURN_TIMEOUT` | `3600` | Hard time limit per turn, in seconds |
| `AGY_TEAMS_DIR` | `~/.agy-teams` | Where state is stored |

## Development

```bash
python tests/run_all.py   # each test runs in its own process with a throwaway state dir
ruff check .
```

## Limitations

- Single machine, single user. There is no auth beyond the localhost bind and the origin check.
- Telemetry depth depends on the runtime. Only `agy` exposes per-step logs.
- The CLI output and agent prompts are in Turkish.

## License

[MIT](LICENSE)
