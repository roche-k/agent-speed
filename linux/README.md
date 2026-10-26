# Agent Speed for Linux (terminal)

A live `top` for your AI agents. Agent Speed reads the transcripts your agents already write on this machine and
prints a self-refreshing table of each active agent's output speed, model, phase, today's output and today's
API-equivalent cost. It is the Linux terminal counterpart of the macOS and Windows apps, and it reuses the same
measurement engine as both.

```text
Agent Speed  ·  live 142.9 tok/s  ·  today 910.8k out  ·  $47.90  ·  3 generating  ·  15:51:02
┌────────────┬─────────────────────────┬────────────────────┬───────┬────────┬──────────┬──────────┐
│SOURCE      │AGENT                    │MODEL               │PHASE  │   TOK/S│     TODAY│      COST│
├────────────┼─────────────────────────┼────────────────────┼───────┼────────┼──────────┼──────────┤
│Codex       │app_trader_relay         │gpt-6.1-sol         │● gen  │    34.8│    257.7k│    $12.41│
│Codex       │  └─ worker              │gpt-6.1-sol         │● gen  │    12.1│     41.2k│     $2.03│
│OpenCode    │agent-speed              │deepseek-v4-flash   │○ idle │    77.3│    271.0k│     $0.66│
└────────────┴─────────────────────────┴────────────────────┴───────┴────────┴──────────┴──────────┘

TODAY BY SOURCE  Codex 639.7k $47.24   OpenCode 271.0k $0.66
Ctrl-C quit  ·  interval 2.0s  ·  warnings: none
```

## Requirements

- Linux.
- Python 3.10 or later (standard library only; no pip packages).
- Optional: the `zstd` command for compressed Codex logs (`sudo apt install zstd`, `sudo dnf install zstd`, or your
  distribution's equivalent). Without it, compressed logs are skipped and the footer shows a warning.

Run it from a repository checkout:

```sh
git clone https://github.com/zoefix/agent-speed.git
cd agent-speed
./linux/agentspeed
```

The CLI imports `spec/tools/reference.py`, so keep the `linux/` and `spec/` folders together. If you move the
checkout, set `AGENT_SPEED_SPEC` to the `spec` folder.

## Usage

```sh
./linux/agentspeed                         # live table, 2 s refresh
./linux/agentspeed --once                  # one plain-text snapshot, then exit
./linux/agentspeed --interval 1            # refresh every second
./linux/agentspeed --sources codex,claude  # only these sources
./linux/agentspeed --ascii --no-color      # terminals without UTF-8 or color
```

`--once` is also the automatic behavior when stdout is not a terminal, so the command is safe in scripts, cron jobs
and pipes.

### Options

| Option | Meaning |
| --- | --- |
| `--interval SECONDS` | Live refresh interval, default `2.0`, minimum `0.5`. |
| `--once` | Print one snapshot and exit. |
| `--sources LIST` | Comma-separated source keys (default: all). Aliases: `claude` → `claudeCode`, `dsh` → `deepseek`, `grok` → `grokBuild`, `workbuddy-ai` → `workbuddyAi`. |
| `--no-color` | Disable ANSI colors. |
| `--ascii` | Use ASCII borders and symbols instead of box drawing and `●`/`○`. |
| `--prices PATH` | Use another price table for today's cost. |
| `--codex PATH` | Codex sessions folder. |
| `--claude PATH` | Claude projects folder (Claude Code and Claude Desktop). |
| `--dsh PATH` | DSH sessions folder. |
| `--opencode PATH` | OpenCode database file or the folder that contains `opencode.db`. |
| `--gemini PATH` | Gemini CLI `tmp` folder (repeatable). |
| `--omp PATH` | omp sessions folder (repeatable). |
| `--antigravity PATH` | Antigravity store or its `conversations` folder (repeatable). |
| `--workbuddy PATH` | WorkBuddy data folder or its `projects` folder. |
| `--workbuddy-ai PATH` | WorkBuddy AI data folder or its `projects` folder. |
| `--zcode PATH` | ZCode data folder, database folder, or `db.sqlite`. |
| `--kimi PATH` | Kimi Code CLI sessions folder. |
| `--grok PATH` | Grok Build sessions folder. |
| `--version` | Print the version and exit. |

## Sources

The same 13 sources as the apps, with the same environment overrides:

| Source | Folder |
| --- | --- |
| Codex (CLI, IDE, desktop) | `~/.codex/sessions` (or `$CODEX_HOME/sessions`) |
| Claude Code | `~/.claude/projects` (or `$CLAUDE_CONFIG_DIR/projects`) |
| Claude Desktop | `~/.claude/projects` |
| DSH | `~/.dsh/sessions` (or `$DSH_HOME/sessions`) |
| OpenCode | `~/.local/share/opencode/opencode.db` (or `$XDG_DATA_HOME/opencode`) |
| Gemini CLI | `~/.gemini/tmp` (or `$GEMINI_CLI_HOME/.gemini/tmp`) |
| omp | `~/.omp/agent/sessions` and every profile under `~/.omp/profiles` |
| Antigravity | `~/.gemini/antigravity-cli`, `~/.gemini/antigravity`, `~/.gemini/antigravity-ide` |
| WorkBuddy | `~/.workbuddy/projects` |
| WorkBuddy AI | `~/.workbuddy-ai/projects` |
| ZCode | `~/.zcode/cli/db/db.sqlite` (or `$ZCODE_DATA_BASE_DIR/.zcode/cli/db`) |
| Kimi Code CLI | `~/.kimi-code/sessions` (or `$KIMI_CODE_HOME/sessions`) |
| Grok Build | `~/.grok/sessions` (or `$GROK_HOME/sessions`) |

## How the numbers are computed

- **Live tok/s** is output tokens divided by the real time the model spent on them, over a three-second window,
  including time to first token. Parallel agents add up; a response still streaming is estimated from that agent's
  recent measured speed and corrected when it completes. This is the same formula as `spec/METRICS.md`.
- **Today** starts at local midnight.
- **Cost** is what the day's tokens would cost at each model's API list prices, in US dollars, from
  `spec/assets/prices.json`. Models without a known price are counted as unpriced.
- **Rows** are agents active in the last ten minutes, plus any agent generating right now. Generating agents come
  first, then by live speed, latest activity and id; sub-agents are indented under their parent.
- **TODAY BY SOURCE** aggregates every session that produced output today, including sessions no longer active.

## Privacy

Read-only and local-only. The CLI never sends network requests, never writes a database and never prints prompts,
conversation content, file contents or project paths. It reads token counts, model names and the project folder name
that the apps already show.

## Troubleshooting

- **No agent logs found** — start an agent, or pass the right folder with `--codex`, `--claude`, `--opencode`, etc.
  `--help` lists every override.
- **`zstd not found: compressed logs skipped`** — install `zstd` if you need archived Codex sessions; live JSONL
  sessions are unaffected.
- **OpenCode database is busy** — the database is locked by another process; the next frame retries automatically.
- **Borders look wrong** — use `--ascii` for terminals without UTF-8.
- **Narrow terminal** — the model column drops below 72 columns, cost below 61, today below 50 and phase below 44;
  source, agent and tok/s always remain.
- **Python too old** — use Python 3.10 or later.

## Tests

```sh
PYTHONPATH=linux python3 -m unittest discover -s linux/tests -v
```
