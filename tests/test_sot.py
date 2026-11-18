import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import sot  # noqa: E402


def card(**kw):
    base = {"id": "s", "inputs": "fixed", "answer": "one", "check": "exact",
            "wrong_cost": "low", "effect": "none", "path": "fixed"}
    base.update(kw)
    return base


def lanes(steps):
    return [(s["id"], s["lane"]) for s in steps]


class RouteTests(unittest.TestCase):
    def test_fixed_single_answer_is_script(self):
        self.assertEqual(lanes(sot.route_step(card())), [("s", "SCRIPT")])

    def test_loose_single_answer_splits_shape_then_run(self):
        out = sot.route_step(card(inputs="loose", check="schema"))
        self.assertEqual(lanes(out), [("s.shape", "THINK"), ("s.run", "SCRIPT")])
        self.assertEqual(out[1]["needs"], ["s.shape"])

    def test_path_depends_is_scout_with_budget(self):
        out = sot.route_step(card(inputs="loose", answer="many", path="depends",
                                  check="rubric", budget={"tools": ["grep"]}))
        self.assertEqual(out[0]["lane"], "SCOUT")
        self.assertEqual(out[0]["budget"]["max_calls"], 12)
        self.assertEqual(out[0]["budget"]["tools"], ["grep"])

    def test_unverifiable_costly_judgment_goes_to_human(self):
        out = sot.route_step(card(inputs="loose", answer="many", check="none", wrong_cost="high"))
        self.assertEqual(out[0]["lane"], "HUMAN")
        self.assertTrue(out[0]["ask"])

    def test_unverifiable_cheap_judgment_gets_a_check_added(self):
        out = sot.route_step(card(inputs="loose", answer="many", check="none", wrong_cost="med"))
        self.assertEqual((out[0]["lane"], out[0]["check"]), ("THINK", "schema"))

    def test_external_costly_fixed_action_is_gated_script(self):
        out = sot.route_step(card(effect="external", wrong_cost="high"))
        self.assertEqual(lanes(out), [("s", "SCRIPT")])
        self.assertEqual(out[0]["gate"], "human")

    def test_external_open_action_splits_decide_and_act(self):
        out = sot.route_step(card(effect="external", inputs="loose", answer="many",
                                  check="none", wrong_cost="high"))
        self.assertEqual(lanes(out), [("s.decide", "HUMAN"), ("s.act", "SCRIPT")])
        self.assertNotIn("gate", out[1])

    def test_dependencies_follow_split_steps_and_example_lints_ready(self):
        with open(os.path.join(HERE, "..", "examples", "steps.json")) as fh:
            plan = sot.route(json.load(fh))
        match = [s for s in plan["steps"] if s["id"] == "match"][0]
        self.assertEqual(match["needs"], ["extract.run"])
        self.assertEqual(sot.lint(plan)["verdict"], "READY")

    def test_bad_field_raises(self):
        with self.assertRaises(sot.BadInput):
            sot.route_step(card(wrong_cost="huge"))


class LintTests(unittest.TestCase):
    def test_catches_unbounded_scout_unchecked_think_and_ungated_payment(self):
        plan = {"steps": [
            {"id": "a", "lane": "SCOUT", "check": "rubric", "budget": {}},
            {"id": "b", "lane": "THINK", "check": "none", "needs": ["a"]},
            {"id": "c", "lane": "SCRIPT", "check": "exact", "effect": "external", "wrong_cost": "high"},
            {"id": "d", "lane": "THINK", "check": "schema", "effect": "external", "needs": ["zzz"]},
        ]}
        res = sot.lint(plan)
        self.assertEqual(res["verdict"], "FIX")
        text = " ".join(res["errors"])
        for needle in ("max_calls", "allow-list", "b: THINK step with no check",
                       "c: costly outside effect", "d: outside effect must run", "'zzz'"):
            self.assertIn(needle, text)


class FingerprintTests(unittest.TestCase):
    def test_json_key_order_and_whitespace_do_not_matter(self):
        self.assertEqual(sot.fingerprint('{"b": 1, "a": [1, 2]}'), sot.fingerprint('{"a":[1,2],"b":1}'))
        self.assertEqual(sot.fingerprint("hello   world\n"), sot.fingerprint("hello world"))
        self.assertNotEqual(sot.fingerprint("a"), sot.fingerprint("b"))


class RatchetTests(unittest.TestCase):
    def test_example_records_give_expected_moves(self):
        recs = sot._load_jsonl(os.path.join(HERE, "..", "examples", "records.jsonl"))
        moves = {r["step"]: r["move"] for r in sot.ratchet(recs)["steps"]}
        self.assertEqual(moves, {"chase": "PROMOTE", "dispute.decide": "KEEP",
                                 "extract.shape": "CACHE", "match": "DEMOTE", "summary": "KEEP"})

    def test_wait_freeze_tighten_split_sample(self):
        def rec(step, lane, **kw):
            r = {"step": step, "lane": lane, "ok": True}
            r.update(kw)
            return r
        recs = [rec("few", "THINK", out="1")] * 2
        recs += [rec("const", "THINK", **{"in": str(i), "out": "same"}) for i in range(5)]
        recs += [rec("flaky", "THINK", ok=(i < 3), **{"in": str(i), "out": str(i)}) for i in range(5)]
        recs += [rec("capped", "SCOUT", trail=["x"], hit_budget=(i < 2)) for i in range(5)]
        recs += [rec("signoff", "HUMAN", edited=False) for _ in range(5)]
        moves = {r["step"]: r["move"] for r in sot.ratchet(recs)["steps"]}
        self.assertEqual(moves, {"few": "WAIT", "const": "FREEZE", "flaky": "TIGHTEN",
                                 "capped": "SPLIT", "signoff": "SAMPLE"})


class CliTests(unittest.TestCase):
    def test_lint_exit_code_reflects_verdict(self):
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump({"steps": [{"id": "h", "lane": "HUMAN", "check": "none"}]}, fh)
        try:
            self.assertEqual(sot.main(["lint", fh.name]), 1)
            self.assertEqual(sot.main(["lint", os.path.join(HERE, "..", "examples", "plan.json")]), 0)
            self.assertEqual(sot.main(["route", "/no/such/file.json"]), 2)
        finally:
            os.unlink(fh.name)


if __name__ == "__main__":
    unittest.main()
