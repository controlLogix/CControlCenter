"""Bounded, read-only access to the existing dashboard API."""
import json
import os
import http.client
import time
import urllib.error
import urllib.parse
import urllib.request

MAX_RESPONSE = 512 * 1024
TIMEOUT = 2.0


class Refused(ValueError):
    pass


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def loads(raw):
    return json.loads(raw, object_pairs_hook=_object,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError("non-finite JSON value")))


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def read(path, query=None):
    base = os.environ.get("AGENTMUX_DASHBOARD", "http://127.0.0.1:8787")
    try:
        parsed = urllib.parse.urlsplit(base)
        if (parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username
                or parsed.password or parsed.query or parsed.fragment):
            raise ValueError("invalid dashboard URL")
        url = base.rstrip("/") + path
        if query:
            url += "?" + urllib.parse.urlencode(query)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        with opener.open(urllib.request.Request(url, headers={"Accept": "application/json"}), timeout=TIMEOUT) as response:
            if response.status != 200:
                raise Refused("dashboard returned HTTP " + str(response.status))
            length = response.headers.get("Content-Length")
            if length is not None and (not length.isdigit() or int(length) > MAX_RESPONSE):
                raise Refused("dashboard response exceeds the size limit or has an invalid length")
            chunks = []
            count = 0
            deadline = time.monotonic() + TIMEOUT
            while True:
                if time.monotonic() > deadline:
                    raise Refused("dashboard response timed out")
                chunk = response.read1(min(65536, MAX_RESPONSE + 1 - count))
                if not chunk:
                    break
                chunks.append(chunk)
                count += len(chunk)
                if count > MAX_RESPONSE:
                    raise Refused("dashboard response exceeds the size limit")
            raw = b"".join(chunks)
            if length is not None and len(raw) != int(length):
                raise Refused("dashboard response ended before its declared length")
        result = loads(raw.decode("utf-8"))
        if not isinstance(result, dict):
            raise Refused("dashboard response must be a JSON object")
        return result
    except urllib.error.HTTPError as exc:
        raise Refused("dashboard returned HTTP " + str(exc.code)) from None
    except (OSError, ValueError, RecursionError, http.client.HTTPException, urllib.error.URLError) as exc:
        if isinstance(exc, Refused):
            raise
        raise Refused("dashboard lookup failed: " + type(exc).__name__) from None


def rows(data, key):
    value = data.get(key)
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise Refused("dashboard response has invalid " + key)
    return value
