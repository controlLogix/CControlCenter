import copy
import json
from pathlib import Path
import unittest

from agentmux_contracts import ContractError, evaluate_transition
from agentmux_contracts.state_models import DEFAULT_MODELS, MAX_REVISION


def request(machine, edge, state=None, revision=0, pending=None):
    state = state or edge["from"]
    return {"schemaVersion": "1.0.0", "machine": machine,
            "ownerSnapshot": {"entityId": "entity-one", "ownerHubId": "hub-one", "scopeId": "project-one",
                              "state": state, "revision": revision, "cancellationPending": state == "cancel_requested" if pending is None else pending},
            "intent": {"entityId": "entity-one", "expectedRevision": revision, "event": edge["event"],
                       "operationId": "operation-one", "payloadDigest": "sha256:" + "a" * 64},
            "authority": {"entityId": "entity-one", "ownerHubId": "hub-one", "scopeId": "project-one",
                          "actorRole": edge["actorRole"], "evidenceRefs": ["fixture:owner-authentication"]},
            "guards": {name: "fixture:" + name for name in edge["requires"]}}


class StateModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.models = json.loads(DEFAULT_MODELS.read_text(encoding="utf8"))["machines"]

    def test_all_edges_and_required_evidence(self):
        count = 0
        for machine, model in self.models.items():
            for edge in model["transitions"]:
                value = request(machine, edge)
                before = copy.deepcopy(value)
                with self.subTest(machine=machine, event=edge["event"], state=edge["from"]):
                    result = evaluate_transition(value)
                    self.assertEqual(result["state"], edge["to"])
                    self.assertEqual(result["revision"], 1)
                    self.assertEqual(value, before)
                    for guard in edge["requires"]:
                        bad = copy.deepcopy(value)
                        del bad["guards"][guard]
                        with self.assertRaises(ContractError):
                            evaluate_transition(bad)
                    bad = copy.deepcopy(value)
                    bad["authority"]["actorRole"] = "untrusted"
                    with self.assertRaises(ContractError):
                        evaluate_transition(bad)
                count += 1
        self.assertEqual(count, 68)

    def test_closed_fields_owner_revision_and_evidence(self):
        edge = self.models["task"]["transitions"][0]
        original = request("task", edge)
        mutations = [lambda v: v.update(extra=True),
                     lambda v: v["authority"].update(scopeId="other"),
                     lambda v: v["intent"].update(expectedRevision=1),
                     lambda v: v["ownerSnapshot"].update(revision=True),
                     lambda v: v["authority"].update(evidenceRefs=[]),
                     lambda v: v["guards"].update(plan_authorized=True),
                     lambda v: v["guards"].update(plan_authorized="   "),
                     lambda v: v["intent"].update(event="unknown"),
                     lambda v: v["guards"].update(unrequested="fixture:unknown")]
        for mutation in mutations:
            value = copy.deepcopy(original)
            mutation(value)
            with self.assertRaises(ContractError):
                evaluate_transition(value)
        value = request("task", edge, revision=MAX_REVISION)
        with self.assertRaises(ContractError):
            evaluate_transition(value)

    def test_cancellation_survives_unknown_result(self):
        edges = self.models["attempt"]["transitions"]
        def pick(event, state):
            return next(e for e in edges if e["event"] == event and e["from"] == state)
        first = evaluate_transition(request("attempt", pick("cancel", "running")))
        self.assertTrue(first["cancellationPending"])
        unknown = evaluate_transition(request("attempt", pick("outcome_unknown", "cancel_requested"), revision=1, pending=True))
        self.assertEqual(unknown["state"], "effect_uncertain")
        self.assertTrue(unknown["cancellationPending"])
        for event in ("reconcile_running", "reconcile_terminal"):
            with self.assertRaises(ContractError):
                evaluate_transition(request("attempt", pick(event, "effect_uncertain"), revision=2, pending=True))
        resumed = evaluate_transition(request("attempt", pick("reconcile_cancel_pending", "effect_uncertain"), revision=2, pending=True))
        self.assertEqual(resumed["state"], "cancel_requested")
        final = evaluate_transition(request("attempt", pick("stop_confirmed", "cancel_requested"), revision=3, pending=True))
        self.assertEqual(final["state"], "cancelled")
        self.assertFalse(final["cancellationPending"])


if __name__ == "__main__":
    unittest.main()
