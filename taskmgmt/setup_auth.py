#!/usr/bin/env python3
"""Configure agentmux authentication. Nothing is echoed; nothing is a CLI argument.

    python3 taskmgmt/setup_auth.py --list
    python3 taskmgmt/setup_auth.py --provider vertex      # shared: project + region
    python3 taskmgmt/setup_auth.py codex-custom           # method: gateway + model
    python3 taskmgmt/setup_auth.py --verify codex-custom
    python3 taskmgmt/setup_auth.py --select codex-custom

TWO LEVELS, and the split is the point
--------------------------------------
A region or an API key belongs to a PROVIDER, not to each CLI that uses it, so
a provider is configured once and every CLI on it inherits the value. Only what
is genuinely method-specific - a model id, and for codex a gateway URL - is stored
per method, namespaced by method id.

An earlier version stored everything flat, so two methods sharing one provider both
wrote a bare `model` key and each silently clobbered the other.

WHERE THINGS GO
---------------
  ~/.agentmux/auth.json   0600   non-secret settings and the active method per CLI:
                                 { active: {}, providers: {}, methods: {} }
  ~/.agentmux/env         0600   secret environment exports only.

Separate files because the dashboard may READ and display the first and must never
touch the second. agentmux SOURCES the env file into each pane rather than
interpolating it into the tmux command, so a key never lands in `ps`, in
`pane_start_command`, or in shell history.

Secrets are read with getpass: not echoed, not a command argument, and never printed
back to confirm. A key you can see in your scrollback is a key in your scrollback.
"""

import argparse
import getpass
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MANIFEST = REPO / "dashboard" / "auth.json"
ROOT = Path.home() / ".agentmux"
SETTINGS = ROOT / "auth.json"
ENV_FILE = ROOT / "env"

# Validators named by settings[].validate in the manifest.
VALIDATORS = {
    "base_url": (
        re.compile(r"https?://[A-Za-z0-9._:\[\]-]+(/[A-Za-z0-9._~/-]*)?\Z"),
        "must be an http(s) URL, no query string and no credentials in it",
    ),
    "gcp_region": (re.compile(r"[a-z]{2}(-[a-z]+)+[0-9]\Z"), "must look like us-east5"),
    "gcp_project": (re.compile(r"[a-z][a-z0-9-]{4,62}\Z"),
                    "lowercase letters, digits and dashes"),
    "model": (re.compile(r"[A-Za-z0-9][A-Za-z0-9._:\[\]/-]{0,200}\Z"),
              "letters, digits and . _ : / - [ ] only"),
    "text": (re.compile(r"[^\x00-\x1f]{1,300}\Z"), "no control characters"),
}
ENV_NAME = re.compile(r"[A-Z][A-Z0-9_]{1,63}\Z")


def die(message):
    sys.exit(f"setup_auth: {message}")


class Manifest:
    def __init__(self):
        try:
            with MANIFEST.open(encoding="utf-8") as fh:
                data = json.load(fh)
        except OSError as err:
            die(f"cannot read {MANIFEST}: {err}")
        except ValueError as err:
            die(f"{MANIFEST} is not valid JSON: {err}")
        self.providers = {p["id"]: p for p in data.get("providers", [])
                          if isinstance(p, dict) and p.get("id")}
        self.methods = {m["id"]: m for m in data.get("methods", [])
                        if isinstance(m, dict) and m.get("id")}
        if not self.providers or not self.methods:
            die("auth.json declares no providers or no methods")
        for method in self.methods.values():
            if method.get("provider") not in self.providers:
                die(f"method {method['id']} names an unknown provider "
                    f"{method.get('provider')!r}")

    def provider_of(self, method_id):
        return self.providers[self.methods[method_id]["provider"]]


def load_settings():
    if not SETTINGS.exists():
        return {"version": 2, "active": {}, "providers": {}, "methods": {}}
    mode = stat.S_IMODE(SETTINGS.lstat().st_mode)
    if mode & 0o077 and not str(SETTINGS).startswith("/mnt/"):
        die(f"{SETTINGS} is mode {mode:o}; run: chmod 600 {SETTINGS}")
    try:
        with SETTINGS.open(encoding="utf-8") as fh:
            data = json.load(fh)
    except ValueError as err:
        die(f"{SETTINGS} is not valid JSON: {err}")
    # Migrate a v1 flat file rather than losing it. v1 kept every attribute under a
    # single "settings" key, which is exactly the collision this version fixes, so the
    # values are parked under _v1_settings and must be re-confirmed per method.
    #
    # NON-DESTRUCTIVE, deliberately. The first version rebuilt the dict from scratch
    # with empty providers{} and methods{}, so a file carrying BOTH a legacy settings
    # blob and real v2 data lost the v2 data on every single load — settings written
    # seconds earlier silently vanished and the method reported itself unconfigured.
    # A migration that discards data is worse than no migration.
    if "settings" in data and data.get("version") != 2:
        legacy = data.pop("settings")
        if legacy:
            print("  note: this auth.json carries v1 flat settings. They are kept under")
            print("        _v1_settings; re-run --provider <id> and <method-id> to")
            print("        confirm them under the new two-level layout.")
            data.setdefault("_v1_settings", legacy)
        data["version"] = 2
    for key in ("active", "providers", "methods"):
        data.setdefault(key, {})
    return data


def write_private(path, text):
    """Write 0600 atomically; the file is never briefly world-readable."""
    path.parent.mkdir(parents=True, exist_ok=True)
    previous = os.umask(0o077)
    try:
        handle, temporary = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.")
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as fh:
                fh.write(text)
            os.chmod(temporary, 0o600)
            os.replace(temporary, path)
        except BaseException:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise
    finally:
        os.umask(previous)


def save_settings(data):
    write_private(SETTINGS, json.dumps(data, indent=2, sort_keys=True) + "\n")
    print(f"  wrote {SETTINGS} (0600)")


def read_env_names_and_lines():
    """Return (names, lines). Values stay inside `lines` and are never printed."""
    if not ENV_FILE.exists():
        return set(), {}
    mode = stat.S_IMODE(ENV_FILE.lstat().st_mode)
    if mode & 0o077 and not str(ENV_FILE).startswith("/mnt/"):
        die(f"{ENV_FILE} is mode {mode:o}; agentmux refuses to source it. "
            f"Run: chmod 600 {ENV_FILE}")
    entries = {}
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        match = re.match(r"\s*export\s+([A-Z][A-Z0-9_]*)=(.*)", line)
        if match:
            entries[match.group(1)] = match.group(2)
    return set(entries), entries


def save_env(entries):
    body = [
        "# agentmux private pane environment. Mode 0600 is enforced: agentmux refuses",
        "# to source this file otherwise.",
        "#",
        "# SOURCED into each pane, never interpolated into a command line, so these",
        "# values do not appear in `ps` or in tmux's pane_start_command.",
        "#",
        "# Written by taskmgmt/setup_auth.py. The dashboard never reads the values - it",
        "# reports variable names, presence and file mode only.",
        "",
    ]
    for name in sorted(entries):
        body.append(f"export {name}={entries[name]}")
    write_private(ENV_FILE, "\n".join(body) + "\n")
    print(f"  wrote {ENV_FILE} (0600) — {len(entries)} variable(s), values not shown")


def shell_quote(value):
    return "'" + value.replace("'", "'\\''") + "'"


def ask_setting(spec):
    key = spec["key"]
    pattern, hint = VALIDATORS.get(spec.get("validate", "text"), VALIDATORS["text"])
    label = spec.get("label", key)
    example = f" (e.g. {spec['example']})" if spec.get("example") else ""
    while True:
        value = input(f"  {label}{example}: ").strip()
        if pattern.match(value):
            return value
        print(f"    rejected: {hint}")


def ask_secret(name):
    while True:
        first = getpass.getpass(f"  {name} (not echoed): ")
        if not first.strip():
            print("    empty; nothing stored. Ctrl-C to abort.")
            continue
        if "\n" in first or "\x00" in first:
            print("    rejected: control characters")
            continue
        if first != getpass.getpass("  repeat to confirm: "):
            print("    the two entries differ; try again")
            continue
        return first.strip()


def collect(specs, store, label):
    """Prompt for any of `specs` not already in `store`. Returns True if changed."""
    changed = False
    for spec in specs:
        key = spec["key"]
        if key in store:
            print(f"  {label} {key} = {store[key]}")
            if input("  keep it? [Y/n] ").strip().lower() in ("", "y", "yes"):
                continue
        store[key] = ask_setting(spec)
        changed = True
    return changed


def codex_home():
    return Path(os.environ.get("CODEX_HOME") or (Path.home() / ".codex"))


def write_codex_profile(method, method_values):
    """Generate $CODEX_HOME/<id>.config.toml for a custom-provider method.

    codex 0.155.0 requires a separate profile FILE - an inline [profiles.x] table in
    config.toml is rejected - and accepts only wire_api = "responses". Any backend
    whose native API is not the Responses API therefore needs a translating gateway
    in front of it, which is what base_url points at.
    """
    spec = method["codex_profile"]
    provider = spec["provider_id"]
    path = codex_home() / f"{method['id']}.config.toml"
    text = f'''# Generated by agentmux: taskmgmt/setup_auth.py {method['id']}
# Regenerate rather than hand-editing.
#
# wire_api MUST be "responses"; codex rejects "chat" outright, so the endpoint below
# has to speak the OpenAI Responses API. A backend that does not will need a
# translating gateway in front of it.
#
# No credential appears in this file. env_key names an environment variable that
# agentmux sources from ~/.agentmux/env (0600) into the pane.

model_provider = "{provider}"
model = "{method_values[spec['model_from']]}"

[model_providers.{provider}]
name = "{spec['provider_name']}"
base_url = "{method_values[spec['base_url_from']]}"
wire_api = "{spec['wire_api']}"
env_key = "{spec['env_key']}"
'''
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    print(f"  wrote {path}")


def missing_for(manifest, method_id, settings, env_names):
    method = manifest.methods[method_id]
    provider = manifest.provider_of(method_id)
    gaps = []
    provider_values = settings["providers"].get(provider["id"], {})
    for spec in provider.get("settings", []):
        if spec["key"] not in provider_values:
            gaps.append(f"{provider['id']}.{spec['key']}")
    for name in provider.get("secrets", []):
        if name not in env_names:
            gaps.append(name)
    method_values = settings["methods"].get(method_id, {})
    for spec in method.get("settings", []):
        if spec["key"] not in method_values:
            gaps.append(f"{method_id}.{spec['key']}")
    return gaps


def configure_provider(provider_id, manifest):
    provider = manifest.providers[provider_id]
    print(f"Configuring provider {provider_id} — {provider.get('label', '')}")
    for note in provider.get("notes", []):
        print(f"  note: {note}")
    users = sorted(m["cli"] for m in manifest.methods.values()
                   if m["provider"] == provider_id)
    if users:
        print(f"  shared by: {', '.join(users)}")

    settings = load_settings()
    store = settings["providers"].setdefault(provider_id, {})
    collect(provider.get("settings", []), store, f"{provider_id}")

    secrets = provider.get("secrets", [])
    if secrets:
        env_names, env_lines = read_env_names_and_lines()
        for name in secrets:
            if not ENV_NAME.match(name):
                die(f"manifest declares an invalid env var name: {name}")
            if name in env_names:
                print(f"  {name} is already set")
                if input("  replace it? [y/N] ").strip().lower() not in ("y", "yes"):
                    continue
            env_lines[name] = shell_quote(ask_secret(name))
        save_env(env_lines)
    elif provider.get("kind") == "oauth":
        print("  nothing to store: the CLI owns this login.")
        for action in provider.get("setup", []):
            print(f"  run: {action['command']}")

    save_settings(settings)
    print(f"\nProvider {provider_id} configured. Methods that use it:")
    env_names, _ = read_env_names_and_lines()
    for method in manifest.methods.values():
        if method["provider"] != provider_id:
            continue
        gaps = missing_for(manifest, method["id"], settings, env_names)
        state = "ready" if not gaps else f"still needs {', '.join(gaps)}"
        print(f"  {method['id']:<20} {state}")
    return 0


def configure_method(method_id, manifest):
    method = manifest.methods[method_id]
    provider = manifest.provider_of(method_id)
    print(f"Configuring {method_id} — {method.get('label', '')}")
    print(f"  provider: {provider['id']} ({provider.get('label', '')})")
    for note in method.get("notes", []):
        print(f"  note: {note}")

    settings = load_settings()
    env_names, _ = read_env_names_and_lines()

    # Shared attributes are the provider's job. Point at it rather than asking here,
    # so the same region or key is never entered twice.
    provider_gaps = [
        g for g in missing_for(manifest, method_id, settings, env_names)
        if not g.startswith(f"{method_id}.")
    ]
    if provider_gaps:
        print(f"\n  Provider {provider['id']} is not configured yet "
              f"(missing {', '.join(provider_gaps)}).")
        print(f"  Configure it once for every CLI that uses it:")
        print(f"    python3 taskmgmt/setup_auth.py --provider {provider['id']}")
        if input("  do that now? [Y/n] ").strip().lower() in ("", "y", "yes"):
            configure_provider(provider["id"], manifest)
            settings = load_settings()
        else:
            print("  continuing; this method will report as not configured.")

    store = settings["methods"].setdefault(method_id, {})
    collect(method.get("settings", []), store, method_id)

    if "codex_profile" in method:
        spec = method["codex_profile"]
        needed = [spec["base_url_from"], spec["model_from"]]
        if all(k in store for k in needed):
            write_codex_profile(method, store)
        else:
            print(f"  skipping the codex profile: missing {', '.join(needed)}")

    settings["active"][method["cli"]] = method_id
    save_settings(settings)

    print()
    print(f"Active method for {method['cli']} is now {method_id}.")
    print(f"  agentmux spawn <name> --cli {method['cli']} --auth {method_id}")
    print(f"  (or omit --auth, since it is this CLI's default now)")
    return verify(method_id, manifest)


def verify(method_id, manifest):
    """Prove the configuration loads rather than assuming it does."""
    method = manifest.methods[method_id]
    settings = load_settings()
    env_names, _ = read_env_names_and_lines()
    problems = missing_for(manifest, method_id, settings, env_names)

    for name in manifest.provider_of(method_id).get("secrets", []):
        if name in env_names:
            print(f"  {name}: present (value not shown)")

    if "codex_profile" in method:
        path = codex_home() / f"{method_id}.config.toml"
        if not path.is_file():
            problems.append(f"codex profile not generated: {path}")
        else:
            print(f"  profile present: {path}")
            # codex ignores unknown config fields unless asked not to, so
            # --strict-config is the only thing that actually validates a profile.
            try:
                proc = subprocess.run(
                    ["codex", "exec", "--strict-config", "--profile", method_id,
                     "--skip-git-repo-check", "noop"],
                    capture_output=True, text=True, stdin=subprocess.DEVNULL,
                    timeout=60, check=False)
                combined = (proc.stdout or "") + (proc.stderr or "")
            except FileNotFoundError:
                combined = ""
                print("  codex not on PATH; skipped the profile validation")
            except subprocess.TimeoutExpired:
                combined = ""
                print("  codex did not answer in 60s; skipped the profile validation")
            if "Error loading config" in combined or "is no longer supported" in combined:
                first = next((ln for ln in combined.splitlines() if ln.strip()), "")
                problems.append(f"codex rejected the profile: {first}")
            elif combined:
                print("  codex loaded the profile (config parsed)")

    if problems:
        for problem in problems:
            print(f"  MISSING: {problem}")
        return 1
    print(f"  {method_id}: configured")
    return 0


def select(method_id, manifest):
    settings = load_settings()
    env_names, _ = read_env_names_and_lines()
    gaps = missing_for(manifest, method_id, settings, env_names)
    if gaps:
        die(f"{method_id} is not configured (missing {', '.join(gaps)}). "
            f"Run: python3 taskmgmt/setup_auth.py {method_id}")
    settings["active"][manifest.methods[method_id]["cli"]] = method_id
    save_settings(settings)
    print(f"  active method for {manifest.methods[method_id]['cli']} is now {method_id}")
    return 0


def show_list(manifest):
    settings = load_settings()
    env_names, _ = read_env_names_and_lines()
    by_provider = {}
    for method in manifest.methods.values():
        by_provider.setdefault(method["provider"], []).append(method)

    for provider_id in sorted(by_provider):
        provider = manifest.providers[provider_id]
        shared = settings["providers"].get(provider_id, {})
        bits = [f"{k}={v}" for k, v in sorted(shared.items())]
        bits += [f"{s}={'set' if s in env_names else 'NOT SET'}"
                 for s in provider.get("secrets", [])]
        print(f"\n{provider_id}  [{provider.get('label', '')}]"
              + (f"\n  shared: {', '.join(bits)}" if bits else ""))
        for method in sorted(by_provider[provider_id], key=lambda m: m["id"]):
            gaps = missing_for(manifest, method["id"], settings, env_names)
            marks = []
            if settings["active"].get(method["cli"]) == method["id"]:
                marks.append("ACTIVE")
            elif not settings["active"].get(method["cli"]) and method.get("default"):
                marks.append("cli default")
            marks.append("ready" if not gaps else f"needs {', '.join(gaps)}")
            print(f"    {method['id']:<20} {method['cli']:<7} [{', '.join(marks)}]")
    print()


def main():
    parser = argparse.ArgumentParser(
        description="Configure agentmux authentication (providers and methods).")
    parser.add_argument("method", nargs="?", help="method id from dashboard/auth.json")
    parser.add_argument("--provider", metavar="ID",
                        help="configure a provider's shared attributes (region, API key)")
    parser.add_argument("--list", action="store_true", help="show everything and its state")
    parser.add_argument("--verify", metavar="ID", help="check a method is fully configured")
    parser.add_argument("--select", metavar="ID", help="make a configured method the default")
    args = parser.parse_args()

    manifest = Manifest()
    ROOT.mkdir(parents=True, exist_ok=True)

    if args.list or not any((args.method, args.provider, args.verify, args.select)):
        show_list(manifest)
        return 0
    if args.provider:
        if args.provider not in manifest.providers:
            die(f"unknown provider: {args.provider}. Run --list.")
        return configure_provider(args.provider, manifest)
    for value in (args.verify, args.select, args.method):
        if value and value not in manifest.methods:
            die(f"unknown method: {value}. Run --list.")
    if args.verify:
        return verify(args.verify, manifest)
    if args.select:
        return select(args.select, manifest)
    return configure_method(args.method, manifest)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit("\nsetup_auth: aborted; nothing was written")
