"""Offline schema resolution. No schema or key URL is fetched from a message."""
from collections import OrderedDict
import hashlib
from pathlib import Path
from threading import RLock

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from .wire import ContractError, _check, strict_loads

DEFAULT_SCHEMA_DIR = Path(__file__).resolve().parents[3] / "contracts" / "v1" / "schemas"
_CACHE = OrderedDict()
_CACHE_LOCK = RLock()
_CACHE_LIMIT = 8


def _validators(root):
    # Read once per request: byte digests detect changes even when mtimes do not.
    loaded = [(path.resolve(), path.read_bytes()) for path in sorted(root.glob("*.schema.json"))]
    identity = tuple((str(path), hashlib.sha256(raw).digest()) for path, raw in loaded)
    with _CACHE_LOCK:
        if identity in _CACHE:
            _CACHE.move_to_end(identity)
            return _CACHE[identity]
        schemas = {}
        for path, raw in loaded:
            schema = strict_loads(raw)
            Draft202012Validator.check_schema(schema)
            schemas[path.name.removesuffix(".schema.json")] = schema
        registry = Registry().with_resources((s["$id"], Resource.from_contents(s)) for s in schemas.values())
        compiled = {name: Draft202012Validator(schema, registry=registry) for name, schema in schemas.items()}
        _CACHE[identity] = compiled
        if len(_CACHE) > _CACHE_LIMIT:
            _CACHE.popitem(last=False)
        return compiled


def validate(schema_name, value, schema_dir=None):
    _check(value)
    root = Path(schema_dir) if schema_dir is not None else DEFAULT_SCHEMA_DIR
    try:
        try:
            validators = _validators(root)
        except Exception:
            raise ContractError("schema_configuration_error") from None
        if schema_name not in validators:
            raise ContractError("unknown_schema")
        validator = validators[schema_name]
        if next(validator.iter_errors(value), None) is not None:
            raise ContractError("schema_invalid")
    except ContractError:
        raise
    except Exception:
        raise ContractError("schema_configuration_error") from None
