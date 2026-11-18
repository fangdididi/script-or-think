#!/usr/bin/env python3
"""script-or-think helper: route steps to lanes, lint a plan, fingerprint outputs, ratchet after runs.

Standard library only. Exit codes: 0 = fine, 1 = problems found, 2 = bad input.
"""
import argparse
import hashlib
import json
import sys
from collections import defaultdict

LANES = ("SCRIPT", "THINK", "SCOUT", "HUMAN")
CHECKS = ("exact", "schema", "rubric", "none")
COSTS = ("low", "med", "high")
DEFAULT_BUDGET = {"max_calls": 12, "tools": []}


class BadInput(Exception):
    pass


def _need(card, key, allowed):
    val = card.get(key)
    if val not in allowed:
        raise BadInput("step %r: field %r must be one of %s (got %r)"
                       % (card.get("id"), key, "/".join(allowed), val))
    return val


def route_step(card):
    """Return a list of plan steps (one card may split into two)."""
    sid = card.get("id")
    if not sid:
        raise BadInput("every step needs an id")
    inputs = _need(card, "inputs", ("fixed", "loose"))
    answer = _need(card, "answer", ("one", "many"))
    check = _need(card, "check", CHECKS)
    cost = _need(card, "wrong_cost", COSTS)
    effect = _need(card, "effect", ("none", "local", "external"))
    path = _need(card, "path", ("fixed", "depends"))
    base = {"does": card.get("does", ""), "wrong_cost": cost, "needs": list(card.get("needs", []))}

    def mk(suffix, lane, why, chk, **extra):
        step = dict(base)
        step.update({"id": sid + suffix, "lane": lane, "why": why, "check": chk})
        step.update(extra)
        return step

    # R1: an outside effect is always performed by a script; deciding it may need thought first.
    if effect == "external":
        act_extra = {"effect": "external"}
        if cost == "high":
            act_extra["gate"] = "human"
        if inputs == "fixed" and answer == "one":
            return [mk("", "SCRIPT", ["R1", "R2"], "exact", **act_extra)]
        decide_lane = "HUMAN" if (check == "none" and cost == "high") else "THINK"
        decide = mk(".decide", decide_lane, ["R1"], check if check != "none" else "schema")
        if decide_lane == "HUMAN":
            decide["ask"] = "Approve or edit the proposed %s" % (card.get("does") or sid)
            act_extra.pop("gate", None)  # the human already decided
        act = mk(".act", "SCRIPT", ["R1"], "exact", **act_extra)
        act["needs"] = [sid + ".decide"]
        return [decide, act]
    # R2: fully specified input with one right answer -> code.
    if inputs == "fixed" and answer == "one":
        return [mk("", "SCRIPT", ["R2"], "exact")]
    # R3: one right answer but messy input -> model shapes, code computes.
    if answer == "one":
        shape = mk(".shape", "THINK", ["R3"], "schema")
        run = mk(".run", "SCRIPT", ["R3"], "exact")
        run["needs"] = [sid + ".shape"]
        return [shape, run]
    # R4: the next call depends on what the last call returned -> bounded sub-agent.
    if path == "depends":
        budget = dict(DEFAULT_BUDGET)
        budget.update(card.get("budget", {}))
        return [mk("", "SCOUT", ["R4"], check if check != "none" else "schema", budget=budget)]
    # R5: open judgment. Unverifiable + costly -> a person decides.
    if check == "none":
        if cost == "high":
            return [mk("", "HUMAN", ["R5"], "none",
                       ask="Decide: %s" % (card.get("does") or sid))]
        return [mk("", "THINK", ["R5"], "schema" if cost == "med" else "rubric")]
    return [mk("", "THINK", ["R5"], check)]


def route(doc):
    steps = doc.get("steps")
    if not isinstance(steps, list) or not steps:
        raise BadInput("input needs a non-empty 'steps' list")
    out, renamed = [], {}
    for card in steps:
        routed = route_step(card)
        renamed[card["id"]] = routed[-1]["id"]
        out.extend(routed)
    for step in out:  # point dependencies at the last piece of a split step
        step["needs"] = [renamed.get(n, n) for n in step["needs"]]
    return {"task": doc.get("task", ""), "steps": out}


def lint(plan):
    errors, warnings, seen = [], [], set()
    steps = plan.get("steps") or []
    by_id = {st.get("id"): st for st in steps}
    if not steps:
        errors.append("plan has no steps")
    for st in steps:
        sid = st.get("id", "?")
        lane = st.get("lane")
        if sid in seen:
            errors.append("%s: duplicate id" % sid)
        for dep in st.get("needs", []):
            if dep not in seen:
                errors.append("%s: needs %r which is not an earlier step" % (sid, dep))
        seen.add(sid)
        if lane not in LANES:
            errors.append("%s: unknown lane %r" % (sid, lane))
            continue
        check = st.get("check")
        if check not in CHECKS:
            errors.append("%s: missing or unknown check" % sid)
        if lane in ("THINK", "SCOUT") and check == "none":
            errors.append("%s: %s step with no check - add a schema or rubric" % (sid, lane))
        if lane == "SCRIPT" and check in ("rubric", "none"):
            warnings.append("%s: SCRIPT step checked by %s - scripts can usually be checked exactly"
                            % (sid, check))
        if lane == "SCOUT":
            b = st.get("budget") or {}
            if not isinstance(b.get("max_calls"), int) or b["max_calls"] <= 0:
                errors.append("%s: SCOUT needs budget.max_calls > 0" % sid)
            if not b.get("tools"):
                errors.append("%s: SCOUT needs an allow-list in budget.tools" % sid)
        if lane == "HUMAN" and not st.get("ask"):
            errors.append("%s: HUMAN step needs an 'ask' (the exact question)" % sid)
        if st.get("effect") == "external" and lane != "SCRIPT":
            errors.append("%s: outside effect must run in a SCRIPT step, not %s" % (sid, lane))
        if st.get("effect") == "external" and st.get("wrong_cost") == "high":
            human_before = any(by_id.get(d, {}).get("lane") == "HUMAN" for d in st.get("needs", []))
            if st.get("gate") != "human" and not human_before:
                errors.append("%s: costly outside effect with no human gate or HUMAN step before it" % sid)
        if lane in ("SCRIPT", "THINK") and not st.get("run"):
            warnings.append("%s: no 'run' yet (command or prompt to fill in)" % sid)
    return {"verdict": "READY" if not errors else "FIX", "errors": errors, "warnings": warnings}


def fingerprint(text):
    """Stable short hash: JSON is canonicalised, plain text has whitespace collapsed."""
    try:
        norm = json.dumps(json.loads(text), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    except ValueError:
        norm = " ".join(text.split())
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:16]


def ratchet(records, min_runs=5):
    by_step = defaultdict(list)
    for r in records:
        if "step" not in r or "lane" not in r:
            raise BadInput("record needs 'step' and 'lane': %r" % r)
        by_step[r["step"]].append(r)
    result = []
    for sid in sorted(by_step):
        rs = by_step[sid]
        lane = rs[-1]["lane"]
        n = len(rs)
        ok_rate = sum(1 for r in rs if r.get("ok")) / n
        row = {"step": sid, "lane": lane, "runs": n, "ok_rate": round(ok_rate, 2)}
        if n < min_runs:
            row.update(move="WAIT", reason="only %d of %d runs recorded" % (n, min_runs))
        elif lane == "THINK":
            outs_by_in = defaultdict(set)
            for r in rs:
                outs_by_in[r.get("in")].add(r.get("out"))
            all_outs = {r.get("out") for r in rs}
            repeated = [k for k in outs_by_in if sum(1 for r in rs if r.get("in") == k) > 1]
            stable = all(len(v) == 1 for v in outs_by_in.values())
            if ok_rate < 0.8:
                row.update(move="TIGHTEN", reason="check failed in %d%% of runs" % round(100 * (1 - ok_rate)))
            elif len(all_outs) == 1:
                row.update(move="FREEZE", reason="same output every run - replace with a constant")
            elif stable and len(repeated) >= 2 and ok_rate == 1:
                row.update(move="CACHE",
                           reason="same input gave same output for %d repeated inputs - reuse stored "
                                  "output by input fingerprint, call the model only for new inputs" % len(repeated))
            else:
                row.update(move="KEEP", reason="outputs vary or too few repeated inputs to judge")
        elif lane == "SCOUT":
            trails = {tuple(r.get("trail", [])) for r in rs}
            capped = sum(1 for r in rs if r.get("hit_budget"))
            if capped / n > 0.2:
                row.update(move="SPLIT", reason="hit its call budget in %d of %d runs" % (capped, n))
            elif len(trails) == 1 and ok_rate == 1 and rs[0].get("trail"):
                row.update(move="PROMOTE", to="SCRIPT",
                           reason="identical tool sequence every run: " + " > ".join(rs[0]["trail"]))
            else:
                row.update(move="KEEP", reason="tool path differs between runs")
        elif lane == "SCRIPT":
            fails = [r for r in rs if not r.get("ok")]
            if len(fails) / n > 0.2 and len({r.get("in") for r in fails}) > 1:
                row.update(move="DEMOTE", to="THINK.shape+SCRIPT",
                           reason="fails on %d different inputs - add a shaping step in front" % len({r.get("in") for r in fails}))
            else:
                row.update(move="KEEP", reason="script is holding")
        else:  # HUMAN
            untouched = all(r.get("ok") and not r.get("edited") for r in rs)
            if untouched:
                row.update(move="SAMPLE", reason="approved unchanged %d times - consider review 1 in N (person decides)" % n)
            else:
                row.update(move="KEEP", reason="person edited or rejected at least once")
        result.append(row)
    moves = [r for r in result if r["move"] not in ("KEEP", "WAIT")]
    return {"steps": result, "proposed_moves": len(moves)}


def _load_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _load_jsonl(path):
    out = []
    with open(path, encoding="utf-8") as fh:
        for i, line in enumerate(fh, 1):
            if line.strip():
                try:
                    out.append(json.loads(line))
                except ValueError:
                    raise BadInput("line %d is not JSON" % i)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(prog="sot.py", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("route", help="step cards -> plan with lanes")
    p.add_argument("steps")
    p = sub.add_parser("lint", help="check a plan before running it")
    p.add_argument("plan")
    p = sub.add_parser("fp", help="fingerprint a file (or - for stdin) for run records")
    p.add_argument("file")
    p = sub.add_parser("ratchet", help="propose lane moves from run records")
    p.add_argument("records")
    p.add_argument("--min-runs", type=int, default=5)
    args = ap.parse_args(argv)
    try:
        if args.cmd == "route":
            res = route(_load_json(args.steps)); code = 0
        elif args.cmd == "lint":
            res = lint(_load_json(args.plan)); code = 0 if res["verdict"] == "READY" else 1
        elif args.cmd == "fp":
            text = sys.stdin.read() if args.file == "-" else open(args.file, encoding="utf-8").read()
            print(fingerprint(text)); return 0
        else:
            res = ratchet(_load_jsonl(args.records), args.min_runs); code = 0
    except (BadInput, OSError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 2
    print(json.dumps(res, indent=2, ensure_ascii=False))
    return code


if __name__ == "__main__":
    sys.exit(main())
