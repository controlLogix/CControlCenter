"""One bounded JSON request and response per line; never echo failed input."""
from datetime import datetime
import json
import sys

from . import (ContractError, canonical_bytes, payload_digest, sign_claims,
               strict_loads, validate, validate_payload, verify_attestation, verify_envelope, evaluate_transition)
from .wire import MAX_BYTES


def request(value):
    op = value["op"]
    if op == "evaluateTransition":
        return evaluate_transition(value["request"])
    if op == "parse":
        return strict_loads(value["raw"])
    if op == "canonical":
        return {"canonical": canonical_bytes(value["value"]).decode("utf-8"),
                "sha256": payload_digest(value["value"])}
    if op == "sign":
        return sign_claims(value["claims"], bytes.fromhex(value["seedHex"]))
    if op == "verify":
        return verify_attestation(value["attestation"], bytes.fromhex(value["publicKeyHex"]),
                                  value["expectedAudience"], datetime.fromisoformat(value["now"]), value["payload"])
    if op == "validate":
        validate(value["schema"], value["value"])
        return True
    if op == "validatePayload":
        validate_payload(value["envelope"])
        return True
    if op == "verifyEnvelope":
        return verify_envelope(value["envelope"], bytes.fromhex(value["publicKeyHex"]),
                               value["expectedAudience"], datetime.fromisoformat(value["now"]))
    raise ContractError("unknown_operation")


def main():
    while line := sys.stdin.buffer.readline(MAX_BYTES + 2):
        try:
            frame = line.removesuffix(b"\n")
            if len(frame) > MAX_BYTES:
                # Discard the rest of this oversized request before accepting another.
                while not line.endswith(b"\n"):
                    line = sys.stdin.buffer.readline(MAX_BYTES + 2)
                    if not line:
                        break
                raise ContractError("size_limit")
            response = {"ok": True, "result": request(strict_loads(frame))}
        except ContractError as exc:
            response = {"ok": False, "error": exc.code}
        except Exception:
            response = {"ok": False, "error": "invalid_request"}
        print(json.dumps(response, ensure_ascii=True, allow_nan=False, separators=(",", ":")), flush=True)


if __name__ == "__main__":
    main()
