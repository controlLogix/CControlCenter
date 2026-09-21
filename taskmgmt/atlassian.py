#!/usr/bin/env python3
"""Minimal Atlassian client for the agentmux orchestration.

Jira for task management, Confluence for documentation. Python 3 stdlib only -
no pip install, same constraint as the dashboard backend.

Config: ~/.agentmux/atlassian.json, mode 0600, on the Linux filesystem (NOT
/mnt/c, where POSIX modes are meaningless). Never printed, never logged.

    {
      "deployment": "cloud",                     // or "server"
      "base_url":   "https://YOURORG.atlassian.net",
      "email":      "you@example.com",           // cloud only
      "api_token":  "...",                       // cloud: API token; server: PAT
      "jira_project":      "AGENT",
      "confluence_space":  "AGENTMUX"
    }

Cloud uses Basic auth (email:api_token) against the v3 REST API.
Server/DC uses Bearer <PAT> against v2. Both are supported because the auth
scheme and the API paths differ - this is not a detail that can be papered over.

Every call supports dry_run, which returns the request it WOULD make instead of
sending it. That is how this module is tested without an instance.
"""

from __future__ import annotations

import base64
import json
import os
import pathlib
import ssl
import urllib.error
import urllib.parse
import urllib.request

CONFIG_PATH = pathlib.Path.home() / ".agentmux" / "atlassian.json"
TIMEOUT = 30

REQUIRED = ("deployment", "base_url", "api_token")


class AtlassianError(RuntimeError):
    """Raised with a message safe to show a user - never contains the token."""


# --------------------------------------------------------------------- config ---

def load_config(path: pathlib.Path | None = None) -> dict:
    p = path or CONFIG_PATH
    if not p.is_file():
        raise AtlassianError(
            f"no config at {p}\n"
            f"Create it with: python3 {pathlib.Path(__file__).parent}/setup_atlassian.py"
        )
    # Refuse a world-readable credential file, same rule as ~/.agentmux/env.
    mode = p.stat().st_mode & 0o777
    if mode not in (0o600, 0o400):
        raise AtlassianError(
            f"{p} is mode {mode:o}; must be 600. Run: chmod 600 {p}"
        )
    try:
        cfg = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        raise AtlassianError(f"{p} is not valid JSON: {exc}") from None
    if not isinstance(cfg, dict):
        raise AtlassianError(f"{p} must contain a JSON object")

    missing = [k for k in REQUIRED if not cfg.get(k)]
    if missing:
        raise AtlassianError(f"{p} is missing: {', '.join(missing)}")
    if cfg["deployment"] not in ("cloud", "server"):
        raise AtlassianError('deployment must be "cloud" or "server"')
    if cfg["deployment"] == "cloud" and not cfg.get("email"):
        raise AtlassianError('cloud deployment requires "email"')
    if not str(cfg["base_url"]).startswith("https://"):
        raise AtlassianError("base_url must be https://")
    cfg["base_url"] = str(cfg["base_url"]).rstrip("/")
    return cfg


def _auth_header(cfg: dict) -> str:
    if cfg["deployment"] == "cloud":
        raw = f"{cfg['email']}:{cfg['api_token']}".encode("utf-8")
        return "Basic " + base64.b64encode(raw).decode("ascii")
    return "Bearer " + cfg["api_token"]


# ---------------------------------------------------------------- transport ---

def request(cfg: dict, method: str, path: str, body: dict | None = None,
            *, dry_run: bool = False) -> dict:
    """One HTTP call. Returns the parsed JSON body, or {} for 204."""
    url = cfg["base_url"] + path
    payload = json.dumps(body).encode("utf-8") if body is not None else None

    if dry_run:
        # Deliberately excludes the Authorization header so a dry run is safe to
        # print, paste into a ticket, or commit.
        return {"dry_run": True, "method": method, "url": url, "body": body}

    req = urllib.request.Request(url, data=payload, method=method)
    req.add_header("Authorization", _auth_header(cfg))
    req.add_header("Accept", "application/json")
    if payload is not None:
        req.add_header("Content-Type", "application/json")

    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx) as resp:
            raw = resp.read()
            if not raw:
                return {}
            return json.loads(raw)
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", "replace")[:600]
        except Exception:
            pass
        hint = ""
        if exc.code == 401:
            hint = " (check email + api_token; Cloud needs an API token, not your password)"
        elif exc.code == 403:
            hint = " (authenticated but not permitted - check project/space permissions)"
        elif exc.code == 404:
            hint = " (wrong base_url, project key, or space key)"
        raise AtlassianError(f"{method} {path} -> HTTP {exc.code}{hint}\n{detail}") from None
    except urllib.error.URLError as exc:
        raise AtlassianError(f"{method} {path} failed to connect: {exc.reason}") from None


# --------------------------------------------------------------------- Jira ---

def _jira_api(cfg: dict) -> str:
    return "/rest/api/3" if cfg["deployment"] == "cloud" else "/rest/api/2"


def _adf(text: str) -> dict:
    """Cloud v3 needs Atlassian Document Format; Server v2 takes plain text."""
    return {
        "type": "doc", "version": 1,
        "content": [
            {"type": "paragraph",
             "content": [{"type": "text", "text": line or " "}]}
            for line in text.split("\n")
        ],
    }


def jira_create(cfg, summary, description="", issue_type="Task",
                labels=None, *, dry_run=False) -> dict:
    project = cfg.get("jira_project")
    if not project:
        raise AtlassianError('config needs "jira_project" to create an issue')
    fields = {
        "project": {"key": project},
        "summary": summary[:255],
        "issuetype": {"name": issue_type},
    }
    if description:
        fields["description"] = (_adf(description)
                                 if cfg["deployment"] == "cloud" else description)
    if labels:
        fields["labels"] = list(labels)
    return request(cfg, "POST", f"{_jira_api(cfg)}/issue",
                   {"fields": fields}, dry_run=dry_run)


def jira_comment(cfg, key, text, *, dry_run=False) -> dict:
    body = {"body": _adf(text) if cfg["deployment"] == "cloud" else text}
    return request(cfg, "POST", f"{_jira_api(cfg)}/issue/{urllib.parse.quote(key)}/comment",
                   body, dry_run=dry_run)


def jira_search(cfg, jql, limit=25, *, dry_run=False) -> dict:
    if cfg["deployment"] == "cloud":
        # Cloud moved search to POST /search/jql
        return request(cfg, "POST", f"{_jira_api(cfg)}/search/jql",
                       {"jql": jql, "maxResults": int(limit),
                        "fields": ["summary", "status", "assignee", "labels"]},
                       dry_run=dry_run)
    q = urllib.parse.urlencode({"jql": jql, "maxResults": int(limit)})
    return request(cfg, "GET", f"{_jira_api(cfg)}/search?{q}", dry_run=dry_run)


def jira_transitions(cfg, key, *, dry_run=False) -> dict:
    return request(cfg, "GET",
                   f"{_jira_api(cfg)}/issue/{urllib.parse.quote(key)}/transitions",
                   dry_run=dry_run)


def jira_transition(cfg, key, transition_id, *, dry_run=False) -> dict:
    return request(cfg, "POST",
                   f"{_jira_api(cfg)}/issue/{urllib.parse.quote(key)}/transitions",
                   {"transition": {"id": str(transition_id)}}, dry_run=dry_run)


# --------------------------------------------------------------- Confluence ---

def _conf_api(cfg: dict) -> str:
    # Cloud serves Confluence under /wiki; Server/DC does not.
    return "/wiki/rest/api" if cfg["deployment"] == "cloud" else "/rest/api"


def confluence_find(cfg, title, *, dry_run=False) -> dict:
    space = cfg.get("confluence_space")
    if not space:
        raise AtlassianError('config needs "confluence_space"')
    q = urllib.parse.urlencode({
        "title": title, "spaceKey": space, "expand": "version",
    })
    return request(cfg, "GET", f"{_conf_api(cfg)}/content?{q}", dry_run=dry_run)


def confluence_upsert(cfg, title, html, *, parent_id=None, dry_run=False) -> dict:
    """Create the page, or update it in place if the title already exists.

    Upsert rather than create, so an orchestrator re-running a job does not
    litter the space with duplicate pages.
    """
    space = cfg.get("confluence_space")
    if not space:
        raise AtlassianError('config needs "confluence_space"')

    existing = None
    if not dry_run:
        found = confluence_find(cfg, title)
        results = found.get("results") or []
        if results:
            existing = results[0]

    payload = {
        "type": "page",
        "title": title,
        "space": {"key": space},
        "body": {"storage": {"value": html, "representation": "storage"}},
    }
    if parent_id:
        payload["ancestors"] = [{"id": str(parent_id)}]

    if existing:
        version = int((existing.get("version") or {}).get("number", 1)) + 1
        payload["version"] = {"number": version}
        return request(cfg, "PUT", f"{_conf_api(cfg)}/content/{existing['id']}",
                       payload, dry_run=dry_run)
    return request(cfg, "POST", f"{_conf_api(cfg)}/content", payload, dry_run=dry_run)


def whoami(cfg, *, dry_run=False) -> dict:
    path = ("/rest/api/3/myself" if cfg["deployment"] == "cloud"
            else "/rest/api/2/myself")
    return request(cfg, "GET", path, dry_run=dry_run)
