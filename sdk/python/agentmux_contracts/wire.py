"""Strict JSON admission and RFC 8785 bytes, independent of transport."""
import hashlib
import json
import math

import rfc8785

MAX_BYTES = 1_048_576
MAX_DEPTH = 64
MAX_SAFE_INTEGER = 9_007_199_254_740_991


class ContractError(ValueError):
    """A stable error code that never includes caller payloads or credentials."""
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _check(value, depth=0):
    if type(value) in (list, dict) and depth >= MAX_DEPTH:
        raise ContractError("depth_limit")
    if value is None or type(value) is bool:
        return
    if type(value) is str:
        try:
            value.encode("utf-8", errors="strict")
        except UnicodeError:
            raise ContractError("invalid_unicode") from None
    elif type(value) is int:
        if abs(value) > MAX_SAFE_INTEGER:
            raise ContractError("unsafe_integer")
    elif type(value) is float:
        if not math.isfinite(value):
            raise ContractError("nonfinite_number")
    elif type(value) is list:
        for item in value:
            _check(item, depth + 1)
    elif type(value) is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise ContractError("invalid_key")
            _check(key, depth + 1)
            _check(item, depth + 1)
    else:
        raise ContractError("non_json_value")


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ContractError("duplicate_key")
        result[key] = value
    return result


def _constant(_):
    raise ContractError("nonfinite_number")


def strict_loads(raw):
    """Reject duplicate keys, invalid Unicode, nonfinite values and excess size/depth."""
    if type(raw) not in (bytes, str):
        raise ContractError("invalid_input_type")
    try:
        if type(raw) is bytes:
            if len(raw) > MAX_BYTES:
                raise ContractError("size_limit")
            raw = raw.decode("utf-8", errors="strict")
        if len(raw.encode("utf-8", errors="strict")) > MAX_BYTES:
            raise ContractError("size_limit")
        value = json.loads(raw, object_pairs_hook=_pairs, parse_constant=_constant)
        _check(value)
        return value
    except ContractError:
        raise
    except UnicodeError:
        raise ContractError("invalid_unicode") from None
    except RecursionError:
        raise ContractError("depth_limit") from None
    except (ValueError, TypeError):
        raise ContractError("invalid_json") from None


def canonical_bytes(value):
    """Return JCS UTF-8 bytes; this is not json.dumps with sorted keys."""
    _check(value)
    try:
        result = rfc8785.dumps(value)
    except (rfc8785.CanonicalizationError, ValueError, OverflowError):
        raise ContractError("canonicalization_failed") from None
    if len(result) > MAX_BYTES:
        raise ContractError("size_limit")
    return result


def payload_digest(value):
    return "sha256:" + hashlib.sha256(canonical_bytes(value)).hexdigest()
