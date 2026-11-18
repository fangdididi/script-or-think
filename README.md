**English** | [简体中文](README.zh-CN.md)

# script-or-think

An agent skill that answers one question for every step of a multi-step job:
**should this be code, a model call, a sub-agent, or a person?**

Before the job runs, each step gets six honest answers (is the input fixed? is there one right answer?
how would a machine check it? what does a mistake cost? does it touch the outside world? is the call
path known?). Five ordered rules turn those answers into a lane - `SCRIPT`, `THINK`, `SCOUT` or
`HUMAN` - and a plan file where every step has a check, every sub-agent has a budget, and every costly
outside action has a person in front of it. After a few runs, the execution records drive a ratchet
that proposes one-notch moves: cache what is stable, freeze what is constant, turn a sub-agent's
repeated path into a script, put a shaping step in front of a script that keeps breaking.

## Why

Agents tend to use the model for everything because it is already running. The result: tokens spent
on sorting and arithmetic, emails and payments decided *and sent* by free-form generation, steps that
"look done" with nothing checking them, and recurring jobs that never get cheaper. The opposite failure
exists too - a rigid script that keeps failing because nobody let a model tidy the input first. This
skill makes the split deliberate, written down and revisable with evidence.

## Features

- **Step cards** - six fields per step: `inputs`, `answer`, `check`, `wrong_cost`, `effect`, `path`.
- **Five routing rules (R1-R5)** - outside effects are always performed by code; messy-input/one-answer
  steps split into *model shapes -> code computes*; unknown call paths become a bounded `SCOUT`;
  unverifiable costly judgments go to a `HUMAN` with one exact question.
- **Decide / act split** - thought chooses what to do, code does it, a gate sits between them when it matters.
- **Plan lint** - `READY` / `FIX`: no unchecked model steps, no unbounded loops, no ungated costly
  effects, no dangling dependencies.
- **Execution records** - one JSONL line per step with input/output fingerprints, so runs can be
  compared and resumed.
- **Ratchet** - `FREEZE`, `CACHE`, `TIGHTEN`, `PROMOTE`, `SPLIT`, `DEMOTE`, `SAMPLE`, `KEEP`, `WAIT`;
  never removes a human gate or moves an outside effect off code by itself.
- Zero-dependency helper `scripts/sot.py` (route / lint / fp / ratchet) with JSON output and
  CI-friendly exit codes; 14 tests.

## Installation

Copy the folder into your agent's skills directory:

| Agent | Location |
|---|---|
| Claude Code | `~/.claude/skills/script-or-think/` (or `.claude/skills/` in a project) |
| Codex | `~/.codex/skills/script-or-think/` |
| Cursor | `.cursor/skills/script-or-think/` in the project, or reference `SKILL.md` from a rule |
| Gemini CLI / others | put the folder anywhere and point the agent at `SKILL.md` |

```bash
git clone https://github.com/fangdididi/script-or-think ~/.claude/skills/script-or-think
```

Chinese users can point the agent at `SKILL.zh-CN.md` instead.

## Usage

Ask your agent things like:

- "Before we build this Monday report routine, route each step - script or model?"
- "Our invoice agent is slow and sometimes wrong. Split it into lanes and lint the plan."
- "We have six weeks of run records - what can we harden now?"

Or run the helper yourself (Python 3.8+, no dependencies):

```bash
python3 scripts/sot.py route examples/steps.json > plan.json   # cards -> lanes
python3 scripts/sot.py lint plan.json                           # READY (0) / FIX (1)
python3 scripts/sot.py fp output.json                           # stable fingerprint for records
python3 scripts/sot.py ratchet examples/records.jsonl           # proposed lane moves
python3 -m unittest discover -s tests                           # run the tests
```

## Example

`examples/steps.json` describes a weekly supplier-invoice job in seven cards. Routing gives:

```
collect         SCRIPT          R2
extract.shape   THINK           R3   model reads many PDF layouts into a schema
extract.run     SCRIPT          R3   code validates totals and dates
match           SCRIPT          R2
chase           SCOUT           R4   15 calls, tools: po_search, mail_search
summary         THINK           R5   rubric added (check was "none", cost low)
pay             SCRIPT + gate   R1   exact payment call shown to a person first
dispute.decide  HUMAN           R1
dispute.act     SCRIPT          R1
```

After five recorded weeks (`examples/records.jsonl`) the ratchet proposes: `chase` -> PROMOTE to a
script (same tool path every week), `extract.shape` -> CACHE, `match` -> DEMOTE (needs a shaping step),
dispute sign-off -> KEEP (a person edited it once).

## File structure

```
script-or-think/
├── SKILL.md              # the skill (English)
├── SKILL.zh-CN.md        # the skill (Chinese)
├── README.md
├── README.zh-CN.md
├── scripts/sot.py        # route / lint / fp / ratchet helper, stdlib only
├── tests/test_sot.py     # 14 unit tests
├── examples/
│   ├── steps.json        # step cards for the invoice job
│   ├── plan.json         # routed plan
│   └── records.jsonl     # five weeks of execution records
└── LICENSE               # MIT
```

## License

MIT © 2026 fangdididi
