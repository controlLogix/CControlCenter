"""GitHub sign-in and write actions, with the `gh` CLI as the only credential store.

THE POSTURE THIS KEEPS. Nowhere in this dashboard does a secret travel from the
browser: methods are selected from the page, credentials are entered in a real
terminal, and ~/.agentmux/env is 0600. A GitHub token is a credential like any
other, so it is never posted here, never rendered here, and never returned by any
endpoint in this module. `gh` already owns a credential store the operator's other
tools use; this drives that rather than building a second one.

HOW SIGN-IN WORKS ANYWAY. `gh auth login --web` runs GitHub's device flow: it
prints a one-time code, waits for you to press Enter, then opens a browser at
github.com/login/device where you type that code. It refuses to run without a
terminal, so this allocates a PTY, reads the one-time code out of the stream and
shows it on the page. The code is not a secret - it is useless without the
operator's own GitHub session - and the token it eventually mints is written by
`gh` into `gh`'s own store, never passing through this process or the page.

IF THERE IS NO PTY (a non-Linux host, a stripped container), the flow is not
faked. `available()` says so and the panel falls back to showing the command to
run in a terminal. A login button that silently does nothing is worse than no
button.

WRITES ARE NARROW AND EXPLICIT. Creating a repository and opening an issue are
the two things worth doing from a dashboard, and both take a confirmation and are
journalled. There is no generic "run gh with these arguments" endpoint: every
argument vector below is built in code from validated fields, so a request cannot
introduce a flag. Nothing here pushes, force-pushes, merges or deletes.
"""

import json
import os
import re
import shutil
import subprocess
import threading
import time

try:
    import pty
    import select
    HAVE_PTY = True
except ImportError:                       # Windows, or a Python built without it
    HAVE_PTY = False

LOGIN_TIMEOUT = 300.0
CODE_RE = re.compile(r"\b([A-Z0-9]{4}-[A-Z0-9]{4})\b")
URL_RE = re.compile(r"https://\S*github\.com/login/device\S*")
# The FIRST character may not be a dash or a dot. `gh repo create <name>` takes the
# name as a POSITIONAL argument, so a name of "--public" would arrive at gh as a
# flag rather than as a name - the one way a validated field on this panel could
# still change what the command does. GitHub rejects such names anyway, so this
# costs nothing and does not depend on gh noticing.
REPO_NAME_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._-]{0,99}\Z")
OWNER_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})\Z")
NWO_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]{1,100}\Z")

# Asked for at login. `repo` covers private repositories, `workflow` lets a run be
# re-dispatched, `read:org` makes an org's repositories visible in the picker.
SCOPES = "repo,workflow,read:org,gist"


class Invalid(ValueError):
    """Operator input the panel refuses. Maps to HTTP 400."""


class Unavailable(RuntimeError):
    """gh is missing, unauthenticated, or the host cannot run the flow. HTTP 503."""


def gh_path():
    return shutil.which("gh") or shutil.which("gh.exe")


def is_windows_gh(binary):
    return bool(binary) and os.path.basename(binary).lower() == "gh.exe"


WINDOWS_LOGIN = ("Sign in on the Windows side in PowerShell or Command Prompt: "
                 f"gh auth login --web --scopes {SCOPES}")


def _run(args, timeout=20, stdin_text=None):
    """Run gh and return stdout. stderr is DISCARDED, deliberately.

    gh writes authentication diagnostics to stderr, and those can name a token's
    host, its source file and occasionally a prefix. None of that should reach a
    browser, so failures are reported as the exit status and the verb that failed.
    """
    binary = gh_path()
    if not binary:
        raise Unavailable("gh is not installed or not on PATH.")
    try:
        done = subprocess.run(
            [binary, *args], capture_output=True, text=True, timeout=timeout,
            # Explicit, because the default is the system codepage: a commit
            # subject or an issue title with a non-ASCII character then raises
            # UnicodeDecodeError out of a reader thread, which surfaces as a
            # server error with no connection to what was actually read.
            encoding="utf-8", errors="replace",
            **({"input": stdin_text} if stdin_text is not None
               else {"stdin": subprocess.DEVNULL}),
            env={**os.environ, "GH_PROMPT_DISABLED": "1", "GH_NO_UPDATE_NOTIFIER": "1",
                 "CLICOLOR": "0", "NO_COLOR": "1"})
    except (OSError, subprocess.SubprocessError):
        raise Unavailable(f"gh {args[0]} did not complete.") from None
    if done.returncode:
        raise Unavailable(f"gh {' '.join(args[:2])} failed (exit {done.returncode}).")
    return done.stdout


def account():
    """Who gh is signed in as, and with what. Never returns or logs a token."""
    binary = gh_path()
    windows = is_windows_gh(binary)
    state = {"cli": bool(binary), "authenticated": False, "login": None,
             "name": None, "url": None, "scopes": [], "rate": None,
             "can_login": HAVE_PTY and bool(binary) and not windows, "hostname": "github.com",
             "scopes_requested": SCOPES.split(",")}
    if not state["cli"]:
        state["message"] = "gh is not installed. Install it, then sign in from here."
        state["command"] = "sudo apt install gh"
        return state
    if windows:
        state["message"] = WINDOWS_LOGIN
        state["command"] = f"gh auth login --web --scopes {SCOPES}"
    try:
        # --include prints the response headers, and X-Oauth-Scopes is the only
        # honest source for what this token may actually do. Asking `gh auth status`
        # instead would mean parsing human-facing output off stderr.
        raw = _run(["api", "--include", "user"], timeout=15)
    except Unavailable as err:
        state["message"] = ("gh is installed but not signed in. " + str(err)
                            if "failed" in str(err) else str(err))
        if windows:
            state["message"] += " " + WINDOWS_LOGIN
        state["command"] = f"gh auth login --web --scopes {SCOPES}"
        return state
    head, _, body = raw.partition("\n\n") if "\n\n" in raw else raw.partition("\r\n\r\n")
    for line in head.splitlines():
        key, _, value = line.partition(":")
        if key.strip().lower() == "x-oauth-scopes":
            state["scopes"] = [s.strip() for s in value.split(",") if s.strip()]
    try:
        user = json.loads(body)
    except ValueError:
        state["message"] = "gh returned an unreadable user record."
        return state
    state.update(authenticated=True,
                 login=str(user.get("login") or "")[:80],
                 name=str(user.get("name") or "")[:120] or None,
                 url=str(user.get("html_url") or "")[:200] or None)
    try:
        rate = json.loads(_run(["api", "rate_limit"], timeout=10))["resources"]["core"]
        state["rate"] = {"remaining": int(rate["remaining"]), "limit": int(rate["limit"]),
                         "reset": int(rate["reset"])}
    except (Unavailable, ValueError, KeyError, TypeError):
        pass
    missing = [s for s in ("repo",) if s not in state["scopes"]]
    if missing and state["scopes"]:
        state["message"] = (f"Signed in, but the token is missing the {', '.join(missing)} "
                            f"scope, so creating repositories will be refused. "
                            f"Sign in again to widen it.")
        if windows:
            state["message"] += " " + WINDOWS_LOGIN
    return state


class Login:
    """One device-flow sign-in, driven over a PTY, readable while it runs.

    At most one at a time per server: two concurrent flows would both be writing
    gh's credential file, and the operator would have no way to tell which code on
    screen belongs to which.
    """

    def __init__(self, journal=None):
        self.journal = journal
        self.lock = threading.Lock()
        self.thread = None
        self.state = "idle"        # idle | starting | waiting | finishing | done | error
        self.code = None
        self.url = "https://github.com/login/device"
        self.error = None
        self.started_at = None
        self.actor = None
        self._cancel = threading.Event()

    def available(self):
        binary = gh_path()
        return HAVE_PTY and bool(binary) and not is_windows_gh(binary)

    def start(self, actor):
        actor = str(actor or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", actor):
            raise Invalid("an operator name is required before signing in")
        if not gh_path():
            raise Unavailable("gh is not installed or not on PATH.")
        if is_windows_gh(gh_path()):
            raise Unavailable(WINDOWS_LOGIN)
        if not HAVE_PTY:
            raise Unavailable(
                "This host cannot run the interactive flow. Run it in a terminal: "
                f"gh auth login --web --scopes {SCOPES}")
        with self.lock:
            if self.state in ("starting", "waiting", "finishing"):
                raise Invalid("a sign-in is already in progress")
            self._cancel = threading.Event()
            self.state = "starting"
            self.code = None
            self.error = None
            self.actor = actor
            self.started_at = time.time()
        self.thread = threading.Thread(target=self._run, args=(self._cancel,),
                                       name="gh-login", daemon=True)
        self.thread.start()
        return self.snapshot()

    def cancel(self):
        self._cancel.set()
        with self.lock:
            if self.state in ("starting", "waiting", "finishing"):
                self.state = "idle"
                self.error = "Sign-in cancelled."
        return self.snapshot()

    def _run(self, cancel):
        primary, secondary = pty.openpty()
        try:
            process = subprocess.Popen(
                [gh_path(), "auth", "login", "--hostname", "github.com", "--web",
                 "--git-protocol", "https", "--scopes", SCOPES],
                stdin=secondary, stdout=secondary, stderr=secondary,
                close_fds=True, start_new_session=True,
                env={**os.environ, "GH_NO_UPDATE_NOTIFIER": "1", "NO_COLOR": "1",
                     "CLICOLOR": "0", "BROWSER": "true"})
        except OSError as err:
            os.close(primary)
            os.close(secondary)
            with self.lock:
                self.state = "error"
                self.error = f"could not start gh ({err.strerror or 'OSError'})"
            return
        os.close(secondary)
        buffer = ""
        pressed = False
        deadline = time.monotonic() + LOGIN_TIMEOUT
        try:
            while not cancel.is_set() and time.monotonic() < deadline:
                ready, _, _ = select.select([primary], [], [], 0.5)
                if ready:
                    try:
                        chunk = os.read(primary, 4096)
                    except OSError:
                        break
                    if not chunk:
                        break
                    buffer = (buffer + chunk.decode("utf-8", "replace"))[-8192:]
                    found = CODE_RE.search(buffer)
                    link = URL_RE.search(buffer)
                    with self.lock:
                        if found and not self.code:
                            self.code = found.group(1)
                            self.state = "waiting"
                        if link:
                            self.url = link.group(0)[:200]
                    if found and not pressed:
                        # gh waits on Enter before it opens a browser. BROWSER=true
                        # above makes that a no-op, so the operator opens the URL
                        # themselves from the page - on the machine they are sitting
                        # at, which is not necessarily this one.
                        pressed = True
                        try:
                            os.write(primary, b"\n")
                        except OSError:
                            pass
                if process.poll() is not None:
                    break
            if process.poll() is None:
                if cancel.is_set():
                    process.terminate()
                else:
                    process.terminate()
                    with self.lock:
                        self.error = "Sign-in timed out before GitHub confirmed the code."
            try:
                code = process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                code = -1
        finally:
            try:
                os.close(primary)
            except OSError:
                pass
        with self.lock:
            if cancel.is_set():
                self.state = "idle"
            elif code == 0:
                self.state = "done"
                self.code = None
                self.error = None
            else:
                self.state = "error"
                self.error = self.error or ("GitHub did not complete the sign-in. "
                                            "Check the code and try again.")
        self._record("signed in" if code == 0 else "sign-in failed")

    def _record(self, outcome):
        if not self.journal:
            return
        try:
            self.journal({"kind": "github", "outcome": outcome, "actor": self.actor,
                          "at": time.time()})
        except Exception:
            pass

    def snapshot(self):
        with self.lock:
            return {"state": self.state, "code": self.code, "url": self.url,
                    "error": self.error, "started_at": self.started_at,
                    "available": self.available(),
                    "command": f"gh auth login --web --scopes {SCOPES}"}


def logout(actor, journal=None):
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", str(actor or "")):
        raise Invalid("an operator name is required")
    # --hostname is required or gh prompts, and a prompt on a pipe hangs.
    _run(["auth", "logout", "--hostname", "github.com"], timeout=20)
    if journal:
        try:
            journal({"kind": "github", "outcome": "signed out", "actor": actor,
                     "at": time.time()})
        except Exception:
            pass
    return account()


# -- write actions ----------------------------------------------------------

def create_repo(body, journal=None):
    """`gh repo create`. The argument vector is built here, never supplied."""
    if not isinstance(body, dict):
        raise Invalid("body must be a JSON object")
    unknown = body.keys() - {"name", "owner", "visibility", "description", "actor",
                             "confirm", "gitignore", "license"}
    if unknown:
        raise Invalid(f"unknown fields: {', '.join(sorted(unknown))}")
    actor = str(body.get("actor") or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", actor):
        raise Invalid("an operator name is required")
    if body.get("confirm") is not True:
        raise Invalid("creating a repository requires an explicit confirmation")
    name = str(body.get("name") or "").strip()
    if not REPO_NAME_RE.match(name):
        raise Invalid("repository name may use letters, digits, dot, dash and underscore")
    owner = str(body.get("owner") or "").strip()
    if owner and not OWNER_RE.match(owner):
        raise Invalid("owner must be a GitHub user or organisation name")
    visibility = str(body.get("visibility") or "private")
    if visibility not in ("private", "public", "internal"):
        raise Invalid("visibility must be private, public or internal")
    description = str(body.get("description") or "").strip()[:350]
    if any(ord(c) < 0x20 for c in description):
        raise Invalid("description contains control characters")

    target = f"{owner}/{name}" if owner else name
    args = ["repo", "create", target, f"--{visibility}"]
    if description:
        args += ["--description", description]
    gitignore = str(body.get("gitignore") or "").strip()
    if gitignore:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9+#.-]{0,39}", gitignore):
            raise Invalid("invalid .gitignore template name")
        args += ["--gitignore", gitignore]
    licence = str(body.get("license") or "").strip()
    if licence:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]{0,39}", licence):
            raise Invalid("invalid licence template name")
        args += ["--license", licence]
    out = _run(args, timeout=45).strip()
    url = next((line.strip() for line in out.splitlines()
                if line.strip().startswith("https://")), f"https://github.com/{target}")
    if journal:
        try:
            journal({"kind": "github", "outcome": "repository created", "actor": actor,
                     "repo": target, "visibility": visibility, "at": time.time()})
        except Exception:
            pass
    return {"ok": True, "repo": target, "url": url[:200],
            "detail": f"Created {target} ({visibility})."}


def create_issue(body, journal=None):
    """`gh issue create` against an existing repository."""
    if not isinstance(body, dict):
        raise Invalid("body must be a JSON object")
    unknown = body.keys() - {"repo", "title", "body", "labels", "actor", "confirm"}
    if unknown:
        raise Invalid(f"unknown fields: {', '.join(sorted(unknown))}")
    actor = str(body.get("actor") or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", actor):
        raise Invalid("an operator name is required")
    if body.get("confirm") is not True:
        raise Invalid("opening an issue requires an explicit confirmation")
    repo = str(body.get("repo") or "").strip()
    if not NWO_RE.match(repo):
        raise Invalid("repository must be given as owner/name")
    title = str(body.get("title") or "").strip()
    if not 1 <= len(title) <= 250 or any(ord(c) < 0x20 for c in title):
        raise Invalid("a title of 1 to 250 printable characters is required")
    text = str(body.get("body") or "")[:8000]
    labels = body.get("labels") or []
    if not isinstance(labels, list) or len(labels) > 10:
        raise Invalid("at most 10 labels")
    args = ["issue", "create", "--repo", repo, "--title", title]
    if text:
        # Through --body-file - a long body on a command line is visible in `ps`.
        args += ["--body-file", "-"]
    for label in labels:
        if not isinstance(label, str) or not re.fullmatch(r"[A-Za-z0-9 :._-]{1,50}", label):
            raise Invalid("a label may use letters, digits, space, colon, dot, dash, underscore")
        args += ["--label", label]
    out = _run(args, timeout=45, stdin_text=text if text else None).strip()
    url = next((line.strip() for line in out.splitlines()
                if line.strip().startswith("https://")), "")
    if journal:
        try:
            journal({"kind": "github", "outcome": "issue opened", "actor": actor,
                     "repo": repo, "title": title, "at": time.time()})
        except Exception:
            pass
    return {"ok": True, "repo": repo, "url": url[:200],
            "detail": f"Opened an issue on {repo}."}
