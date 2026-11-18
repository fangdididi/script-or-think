---
name: script-or-think
description: Before an agent runs a multi-step job, split it into steps and route each one to the right lane - SCRIPT (deterministic code or tool call), THINK (one model judgment with an output check), SCOUT (a bounded sub-agent loop), or HUMAN (a person decides) - using six explicit questions per step. Produces a plan file with a check on every step and a human gate before costly outside effects, then after several runs reads the execution records and proposes one-notch lane moves (cache, freeze, promote a stable sub-agent path to a script, demote a brittle script, sample a rubber-stamp approval). Use when designing a skill, workflow, pipeline or recurring agent task, when an agent "does everything with the model", when a job is slow, costly or flaky, or when someone asks "should this be a script or a prompt?".
---

# Script or Think

## What this is

A routing gate you run **before** a multi-step agent job, and a ratchet you run **after** a few runs of it.

Every step of a job is one of four kinds of work:

| Lane | Who does it | Good for | Bad for |
|---|---|---|---|
| `SCRIPT` | code, a CLI, an API call with fixed arguments | anything with one right answer from fully specified input; anything that touches the outside world | reading messy input, choosing among options |
| `THINK` | one model call with a stated output shape | reading loose input, classifying, drafting, summarising | arithmetic, sorting, copying, counting, sending |
| `SCOUT` | a sub-agent that may call tools in a loop, inside a call budget and tool allow-list | investigations where the next call depends on the last answer | anything whose path is already known |
| `HUMAN` | a person, asked one precise question | judgments nobody can check mechanically where a mistake is expensive | anything a check could catch |

The skill makes the choice explicit, writes it down with the reason, and gives every step a way to be checked.

## The problem it solves

Agents default to the model for everything because the model is the thing that is already running. That produces jobs that:

- **burn tokens on deterministic work** - the model re-sorts a CSV, adds up totals, renames files, or formats dates, and is occasionally wrong at it;
- **are flaky in the wrong places** - the step that sends the email or posts the payment is decided *and performed* by free-form generation;
- **can't be verified** - a step "looks done" but nothing checks its output, so errors flow downstream silently;
- **never get cheaper** - a step that gave the same answer fifty runs in a row is still a model call on run fifty-one;
- or the opposite: **a brittle script** that keeps failing on input variety someone should have let the model normalise first.

## When to use

- Designing a new skill, workflow, pipeline, cron job or agent routine with more than two steps.
- Reviewing an existing one that is slow, expensive, flaky, or hard to debug.
- Someone asks "should this be a script or a prompt?", "do we need an agent for this?", "where should the human sign off?".
- After five or more runs of a recurring job, to decide what to harden.

Skip it for a one-off two-step task; just do it.

## Instructions

### 1. Write the step cards

Break the job into steps of one action each (aim for 4-12). For each step fill a card with six answers. Be honest; "loose" and "many" are not failures.

| Field | Question | Values |
|---|---|---|
| `inputs` | Is everything the step needs present in a known shape? | `fixed` / `loose` |
| `answer` | Given the inputs, is there exactly one correct output? | `one` / `many` |
| `check` | How could a machine tell the output is right? | `exact` (equality, test, checksum) / `schema` (shape and ranges) / `rubric` (a written list a second model or person scores) / `none` |
| `wrong_cost` | What does a wrong output cost if nobody notices? | `low` / `med` / `high` |
| `effect` | What does the step change? | `none` / `local` (files in the workspace) / `external` (messages, money, tickets, deploys, anything other people see) |
| `path` | Do you know the sequence of calls in advance? | `fixed` / `depends` (next call depends on what the last one returned) |

Add `id`, a one-line `does`, and `needs` (ids of earlier steps). For `path: depends` add a `budget` with `max_calls` and the `tools` allow-list.

Save as `steps.json` (see `examples/steps.json`).

### 2. Route each step

Apply the rules in order; the first that matches wins.

- **R1 Outside effect.** The act itself is always a `SCRIPT`: an exact call with arguments you can show. If deciding *what* to send needs judgment, split into `<id>.decide` (THINK, or HUMAN when unverifiable and costly) and `<id>.act` (SCRIPT). When `wrong_cost` is `high` and no person decided, the act gets `gate: human` - show the exact call and wait for a yes.
- **R2 Fixed input, one answer.** `SCRIPT`. If no script exists, writing one is the step; the model may author it once, but it does not *perform* the step.
- **R3 Loose input, one answer.** Split: `<id>.shape` (THINK turns mess into a strict schema) then `<id>.run` (SCRIPT computes). The model reads; code counts.
- **R4 Path depends.** `SCOUT` with a call budget (default 12) and a tool allow-list. It returns a structured finding, not a transcript.
- **R5 Open judgment.** `THINK` with the declared check. If the check is `none`: add `rubric` when cost is low, `schema` when medium, and route to `HUMAN` with an exact question when high.

Run `python3 scripts/sot.py route steps.json > plan.json` to apply the rules mechanically, then read the result and override where you know better - write the reason into `why`.

### 3. Fill and lint the plan

For each plan step add `run`: the command for SCRIPT, the prompt plus output schema for THINK, the brief for SCOUT. HUMAN steps carry `ask`, one question answerable in under a minute.

Run `python3 scripts/sot.py lint plan.json`. It returns `READY` or `FIX` (exit 1) and catches:

- a THINK or SCOUT step with no check;
- a SCOUT with no call budget or no tool allow-list;
- a HUMAN step without a precise `ask`;
- an outside effect performed by anything other than a SCRIPT;
- a costly outside effect with neither `gate: human` nor a HUMAN step right before it;
- dependencies on unknown or later steps, and duplicate ids.

Do not run the job until the plan is `READY`.

### 4. Run and record

Execute the steps in order. After each one, run its check; a failed check stops the run at that step (do not "continue and fix later"). Append one line per step to `records.jsonl`:

```json
{"run": "2026-11-18", "step": "extract.shape", "lane": "THINK", "in": "<fp of input>", "out": "<fp of output>", "ok": true}
```

`python3 scripts/sot.py fp FILE` gives a stable fingerprint (JSON key order and whitespace ignored). SCOUT lines add `trail` (tool names in order) and `hit_budget`; HUMAN lines add `edited` (did the person change the proposal?).

Keep intermediate artifacts (the shaped JSON, the scout finding) next to the record so a failed run can be resumed from the last good step.

### 5. Ratchet after five runs

Run `python3 scripts/sot.py ratchet records.jsonl`. It proposes at most one move per step:

| Lane | Move | When |
|---|---|---|
| THINK | `FREEZE` | identical output every run - replace with a constant |
| THINK | `CACHE` | same input always gave the same output - reuse by fingerprint, call the model only for new inputs |
| THINK | `TIGHTEN` | the check failed in more than 20% of runs - sharpen the prompt or the schema |
| SCOUT | `PROMOTE` -> SCRIPT | the same tool sequence every run - write it down as a fixed script |
| SCOUT | `SPLIT` | hit its budget in more than 20% of runs - the question is too big |
| SCRIPT | `DEMOTE` -> THINK.shape + SCRIPT | fails on several different inputs - put a shaping step in front |
| HUMAN | `SAMPLE` | approved unchanged every time - *suggest* reviewing 1 in N; a person decides, never the agent |
| any | `WAIT` / `KEEP` | not enough runs, or nothing to change |

Apply moves one at a time, re-lint, and keep the old lane for one run as a fallback. Never ratchet a step with an outside effect away from SCRIPT, and never remove a human gate on your own.

### 6. Report

Close with a short table: step, lane, why, check, and any proposed move. That table is the plan's documentation.

## Worked examples

### A. Weekly supplier invoices (`examples/`)

Seven cards become nine plan steps:

| Plan step | Lane | Rule | Note |
|---|---|---|---|
| collect | SCRIPT | R2 | copy PDFs from a folder - no model needed |
| extract.shape | THINK | R3 | read vendor/number/date/total from many layouts into a schema |
| extract.run | SCRIPT | R3 | validate totals, parse dates, write the table |
| match | SCRIPT | R2 | join against open purchase orders |
| chase | SCOUT | R4 | look up why an invoice does not match; 15 calls, two tools |
| summary | THINK | R5 | note for the finance lead; check was `none`, cost low -> rubric added |
| pay | SCRIPT + gate | R1 | exact payment call shown to a person first |
| dispute.decide | HUMAN | R1 | which vendors to contact and what to say |
| dispute.act | SCRIPT | R1 | send exactly what was approved |

After five weeks the ratchet says: `chase` always ran `po_search > mail_search` -> PROMOTE to a script; `extract.shape` gave identical results for re-sent invoices -> CACHE; `match` failed on two different weeks -> DEMOTE (vendor names need normalising first); the dispute sign-off was edited once -> KEEP the human.

### B. "Summarise our open GitHub issues every Monday"

- list issues -> SCRIPT (`gh issue list --json ...`), R2.
- group them into themes -> THINK with schema `{theme: [issue numbers]}`, check = every issue appears exactly once (a script can verify that), R5.
- count per theme and sort -> SCRIPT, R2 (the model must not count).
- write the post -> THINK, rubric "mentions every theme, under 200 words, no promises".
- post to Slack -> SCRIPT with `gate: human`, R1.

### C. When the answer is "no agent"

A team wanted an agent to "rename screenshots by date". Every card came out `fixed / one / exact / low / local / fixed`. The whole job routed to SCRIPT, and the plan was one shell loop. That is a valid result.

## Tips

- If you cannot say how a step's output would be checked, the step is too vague - split it until you can.
- "The model can write the script" is fine; "the model can be the script" is the smell.
- Split decide from do: thought picks *what*, code performs *it*, a person stands between them when it matters.
- A SCOUT's budget is part of its spec. An unbounded loop is not a plan.
- Fingerprint inputs as well as outputs, or the ratchet cannot tell stable from lucky.
- Five runs is a floor, not a target; ratchet costly steps only with more evidence.
- Keep `why` short and honest - future you will want to know whether a lane was chosen or defaulted.
