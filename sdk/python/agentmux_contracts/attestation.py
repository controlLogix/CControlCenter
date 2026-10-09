"""Ed25519 integrity and bounded admission checks, not a grant authority."""
import base64
from datetime import datetime, timezone
import hmac

from nacl.exceptions import BadSignatureError
from nacl.signing import SigningKey, VerifyKey

from .wire import ContractError, canonical_bytes, payload_digest
from .validation import validate, validate_payload


def sign_claims(claims, seed32bytes):
    if type(seed32bytes) is not bytes or len(seed32bytes) != 32:
        raise ContractError("invalid_signing_key")
    signature = SigningKey(seed32bytes).sign(canonical_bytes(claims)).signature
    return base64.urlsafe_b64encode(signature).decode("ascii").rstrip("=")


def _timestamp(value):
    try:
        result = datetime.fromisoformat(value)
        if result.utcoffset() != timezone.utc.utcoffset(result):
            raise ValueError()
        return result
    except (ValueError, TypeError, AttributeError):
        raise ContractError("invalid_timestamp") from None


def verify_attestation(attestation, public_key32bytes, expected_audience, now, payload):
    """The caller must select an enrolled key and subsequently check current grants."""
    validate("ingress-attestation", attestation)
    if type(public_key32bytes) is not bytes or len(public_key32bytes) != 32:
        raise ContractError("invalid_verification_key")
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() != timezone.utc.utcoffset(now):
        raise ContractError("invalid_clock")
    claims = attestation["claims"]
    try:
        signature = base64.b64decode(attestation["signature"] + "==", altchars=b"-_", validate=True)
        VerifyKey(public_key32bytes).verify(canonical_bytes(claims), signature)
    except (ValueError, BadSignatureError):
        raise ContractError("signature_invalid") from None
    if claims["audience"] != expected_audience:
        raise ContractError("audience_mismatch")
    if any(claims[key]["ownerHubId"] != claims["issuerHubId"] for key in ("signingKeyRef", "authenticatedTransportRef")):
        raise ContractError("issuer_mismatch")
    issued = _timestamp(claims["issuedAt"])
    expiry = _timestamp(claims["expiresAt"])
    deadline = _timestamp(claims["operation"]["deadline"])
    sent = _timestamp(claims["sentAt"])
    if not issued <= now < expiry <= deadline or issued >= expiry or sent > now:
        raise ContractError("attestation_time_invalid")
    if not hmac.compare_digest(claims["operation"]["payloadDigest"], payload_digest(payload)):
        raise ContractError("payload_digest_mismatch")
    return claims


def verify_envelope(envelope, public_key32bytes, expected_audience, now):
    validate("message-envelope", envelope)
    claims = verify_attestation(envelope["ingressAttestation"], public_key32bytes,
                                expected_audience, now, envelope["payload"])
    for key in ("operation", "messageId", "kind", "contractId", "contractMajor",
                "sourceHubId", "sourceInstanceId", "sentAt", "correlationId"):
        if claims[key] != envelope[key]:
            raise ContractError("envelope_binding_mismatch")
    if claims["audience"] != {"hubId": envelope["destinationHubId"],
                              "serviceId": envelope["destinationServiceId"]}:
        raise ContractError("audience_mismatch")
    validate_payload(envelope)
    return claims
