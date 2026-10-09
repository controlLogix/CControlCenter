"""Pure owner-snapshot model oracle. Supplied evidence is not authentication."""
import os
from pathlib import Path
import re

from .wire import ContractError, _check, strict_loads

MAX_REVISION = 9007199254740991
DEFAULT_MODELS = Path(__file__).resolve().parents[3] / "contracts/v1/models/state-machines.json"


def _require(condition):
    if not condition:
        raise ContractError("transition_invalid")


def _closed(value, keys):
    _require(isinstance(value, dict) and set(value) == set(keys))


def _identifier(value):
    return isinstance(value, str) and re.fullmatch(r"[a-z][a-z0-9_-]{0,95}", value) is not None


def _reference(value):
    return isinstance(value, str) and 0 < len(value) <= 512 and re.search(
        r"[^\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]", value) is not None


def _revision(value):
    # JSON has one numeric type: 3 and 3.0 denote the same safe integer.
    return type(value) in (int, float) and 0 <= value <= MAX_REVISION and value == int(value)


def _models(path):
    try:
        document = strict_loads(Path(path).read_bytes())
        _require(document["schemaVersion"] == "1.0.0")
        machines = document["machines"]
        _require(set(machines) == {"plugin", "task", "delegation", "attempt", "effect"})
        _require(sum(len(m["transitions"]) for m in machines.values()) == 68)
        for model in machines.values():
            _require(model["initial"] in model["states"] and len(set(model["states"])) == len(model["states"]))
            edges = set()
            for edge in model["transitions"]:
                _closed(edge, ["from", "event", "to", "actorRole", "requires"])
                _require(edge["from"] in model["states"] and edge["to"] in model["states"])
                key = (edge["from"], edge["event"])
                _require(key not in edges and len(edge["requires"]) == len(set(edge["requires"])))
                edges.add(key)
        return machines
    except Exception:
        raise ContractError("model_configuration_invalid") from None


def evaluate_transition(request, models_path=None):
    """Return a candidate snapshot; never mutate input or persist a transition."""
    _check(request)
    _closed(request, ["schemaVersion", "machine", "ownerSnapshot", "intent", "authority", "guards"])
    _require(request["schemaVersion"] == "1.0.0")
    models = _models(models_path or os.environ.get("AGENTMUX_STATE_MODELS", DEFAULT_MODELS))
    _require(isinstance(request["machine"], str) and request["machine"] in models)
    model = models[request["machine"]]
    owner, intent, authority, guards = (request[k] for k in ("ownerSnapshot", "intent", "authority", "guards"))
    _closed(owner, ["entityId", "ownerHubId", "scopeId", "state", "revision", "cancellationPending"])
    _closed(intent, ["entityId", "expectedRevision", "event", "operationId", "payloadDigest"])
    _closed(authority, ["entityId", "ownerHubId", "scopeId", "actorRole", "evidenceRefs"])
    for obj, keys in ((owner, ["entityId", "ownerHubId", "scopeId", "state"]),
                      (intent, ["entityId", "event", "operationId"]),
                      (authority, ["entityId", "ownerHubId", "scopeId", "actorRole"])):
        _require(all(_identifier(obj[key]) for key in keys))
    _require(owner["state"] in model["states"])
    _require(_revision(owner["revision"]) and _revision(intent["expectedRevision"]))
    _require(owner["revision"] == intent["expectedRevision"] and owner["revision"] < MAX_REVISION)
    _require(type(owner["cancellationPending"]) is bool)
    _require(all(owner[key] == authority[key] for key in ("entityId", "ownerHubId", "scopeId")))
    _require(owner["entityId"] == intent["entityId"])
    _require(isinstance(intent["payloadDigest"], str) and re.fullmatch(r"sha256:[0-9a-f]{64}", intent["payloadDigest"]) is not None)
    refs = authority["evidenceRefs"]
    _require(isinstance(refs, list) and 0 < len(refs) <= 64 and all(_reference(x) for x in refs))
    _require(len(set(refs)) == len(refs))
    pending = owner["cancellationPending"]
    # A terminal report cannot erase cancellation or strand it in a non-cancel state.
    _require(owner["state"] != "cancel_requested" or pending)
    _require(not pending or owner["state"] in ("cancel_requested", "effect_uncertain"))
    _require(not pending or intent["event"] not in ("reconcile_running", "reconcile_terminal", "validate"))
    edge = next((e for e in model["transitions"] if e["from"] == owner["state"] and e["event"] == intent["event"]), None)
    _require(edge is not None and edge["actorRole"] == authority["actorRole"])
    _require(isinstance(guards, dict) and set(guards) == set(edge["requires"]) and all(_reference(x) for x in guards.values()))
    next_pending = edge["to"] == "cancel_requested" or (pending and edge["to"] != "cancelled")
    return {"machine": request["machine"], "entityId": owner["entityId"], "ownerHubId": owner["ownerHubId"],
            "scopeId": owner["scopeId"], "fromState": owner["state"], "state": edge["to"],
            "previousRevision": int(owner["revision"]), "revision": int(owner["revision"]) + 1,
            "cancellationPending": next_pending, "operationId": intent["operationId"],
            "payloadDigest": intent["payloadDigest"], "event": intent["event"],
            "evidenceRefs": list(refs), "guardEvidence": dict(guards)}
