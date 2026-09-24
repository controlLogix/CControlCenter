"""Getting a person's attention when the harness needs it.

THE GAP THIS FILLS. run.py::record_notice already journals and writes the orchestrator
inbox, and its docstring names the bug it was written for: "The one message whose entire
purpose is to reach a human was the one that could vanish silently." But both of those
destinations are files. Nothing read them except the dashboard, if it happened to be
open, on the right tab. A run that stops and waits for an operator who is not looking
waits forever, and the operator gate in front of completion made that the normal case
rather than the rare one.

THE RULE HERE: A NOTIFICATION IS NEVER THE RECORD. The ledger is the record. Every
channel below is allowed to fail, is bounded in time, and reports its failure rather
than raising - because a toast that could not be drawn must never be able to stop a run
from completing. `deliver()` returns what happened on each channel and the caller
decides whether that is worth saying out loud.

WHY NO TRANSPORT IS BUNDLED. There is no ntfy client, no Pushover, no SMTP, no webhook.
Those are opinions about someone else's infrastructure and each one is a dependency,
a credential store and a failure mode this repo would then own. Instead there is one
command hook: a program of your choosing, handed the subject and body on stdin. Wire it
to whatever you already use.

WHAT IS WORTH INTERRUPTING SOMEONE FOR is decided by the caller, not here, but the bar
is stated once so it stays consistent: a run that has stopped and is waiting on a
person, a card that has been parked after three failed reviews, an agent that died
mid-job, and a whole orchestration finishing. Not per-job progress, not spawns, not
passing verdicts. A notification you did not need is annoying in a way that accumulates,
and the cost of that is the ones you do need being ignored.
"""
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

SUBJECT_MAX = 200
BODY_MAX = 1500
COMMAND_TIMEOUT_S = 20
TOAST_TIMEOUT_S = 25

# Where the desktop lives, when there is one. WSL reaches the Windows toast API through
# interop; on a headless plant box there is no powershell.exe and toast() says so
# instead of pretending.
POWERSHELL = "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"


def one_line(text, limit):
    return " ".join(str(text or "").split())[:limit]


# ── the desktop toast ────────────────────────────────────────────────────────

def powershell_path():
    """The interop path to powershell.exe, or None when this box has no desktop."""
    if os.environ.get("AGENTMUX_NO_TOAST") == "1":
        return None                      # suites and headless runs opt out here
    override = os.environ.get("AGENTMUX_POWERSHELL")
    if override:
        return override if Path(override).is_file() else None
    return POWERSHELL if Path(POWERSHELL).is_file() else None


TOAST_SCRIPT = """
$ErrorActionPreference = 'Stop'
try {
  [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
  [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom, ContentType = WindowsRuntime] | Out-Null
  $template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent(
      [Windows.UI.Notifications.ToastTemplateType]::ToastText02)
  $nodes = $template.GetElementsByTagName('text')
  $nodes.Item(0).AppendChild($template.CreateTextNode($env:AGENTMUX_TOAST_TITLE)) | Out-Null
  $nodes.Item(1).AppendChild($template.CreateTextNode($env:AGENTMUX_TOAST_BODY)) | Out-Null
  $toast = [Windows.UI.Notifications.ToastNotification]::new($template)
  [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier(
      $env:AGENTMUX_TOAST_APP).Show($toast)
  Write-Output 'ok'
  exit 0
} catch {
  Write-Output ('toast failed: ' + $_.Exception.Message)
  exit 1
}
""".strip()


def toast(subject, body, urgency="info"):
    """Raise a desktop notification. Returns (ok, reason).

    BurntToast is not installed and this deliberately does not require it: a channel
    that depends on a module the operator has to install is a channel that is silently
    off until the day it is needed. WinRT is in the OS.

    THE TEXT TRAVELS IN THE ENVIRONMENT, never in the script and never in argv. A
    subject here carries a reviewer's free-text reason, and interpolating that into a
    PowerShell string is how a notification becomes code execution. (`-Command` cannot
    bind a `param()` block anyway - the first version of this passed -Subject and -Body
    and PowerShell silently ignored both, so the toast appeared with no text in it.)
    """
    shell = powershell_path()
    if not shell:
        return False, "no desktop on this box (powershell.exe not reachable)"
    tag = {"error": "Error", "warn": "Warning"}.get(urgency, "Information")
    env = dict(os.environ)
    env["AGENTMUX_TOAST_TITLE"] = one_line(f"agentmux {tag}: {subject}", SUBJECT_MAX)
    env["AGENTMUX_TOAST_BODY"] = one_line(body, 300) or one_line(subject, 300)
    env["AGENTMUX_TOAST_APP"] = "agentmux"
    # WSLENV is how a variable set on the Linux side reaches a Windows process across
    # interop. Without it the script reads three empty strings and quietly toasts
    # nothing, which is worse than failing - it looks like it worked.
    existing = env.get("WSLENV", "")
    names = "AGENTMUX_TOAST_TITLE:AGENTMUX_TOAST_BODY:AGENTMUX_TOAST_APP"
    env["WSLENV"] = f"{existing}:{names}" if existing else names
    try:
        proc = subprocess.run(
            [shell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-Command", TOAST_SCRIPT],
            capture_output=True, text=True, timeout=TOAST_TIMEOUT_S, errors="replace",
            env=env)
    except subprocess.TimeoutExpired:
        return False, f"powershell did not answer within {TOAST_TIMEOUT_S}s"
    except (OSError, subprocess.SubprocessError) as err:
        return False, f"powershell could not be run ({type(err).__name__})"
    out = one_line(proc.stdout or proc.stderr or "powershell failed", 200)
    if proc.returncode != 0 or out != "ok":
        return False, out
    return True, ""


# ── the command hook ─────────────────────────────────────────────────────────

def run_command(command, subject, body, urgency="info", ref=None):
    """Hand the notice to a program of the operator's choosing. Returns (ok, reason).

    THE PAYLOAD GOES ON STDIN, NOT IN ARGV. A subject can carry a reviewer's free-text
    reason; splicing that into a command line makes every notification an injection
    site. The command is split with shlex ONCE, from configuration a person typed, and
    never rebuilt from the message.

    shell=False for the same reason. If you want a pipeline, put it in a script and
    name the script here - then the shell metacharacters are yours and deliberate,
    rather than something an agent's verdict text could introduce.
    """
    if not command or not str(command).strip():
        return False, "no command configured"
    try:
        argv = shlex.split(str(command))
    except ValueError as err:
        return False, f"command is not parseable: {err}"
    if not argv:
        return False, "command is empty"
    payload = json.dumps({
        "subject": one_line(subject, SUBJECT_MAX),
        "body": str(body or "")[:BODY_MAX],
        "urgency": urgency, "ref": ref, "source": "agentmux",
    })
    env = dict(os.environ)
    # Also in the environment, because a one-line hook is usually a curl and reading
    # stdin is the awkward part. Bounded, and never used to build a command.
    env["AGENTMUX_NOTIFY_SUBJECT"] = one_line(subject, SUBJECT_MAX)
    env["AGENTMUX_NOTIFY_URGENCY"] = urgency
    env["AGENTMUX_NOTIFY_REF"] = str(ref or "")
    try:
        proc = subprocess.run(argv, input=payload, capture_output=True, text=True,
                              timeout=COMMAND_TIMEOUT_S, errors="replace", env=env)
    except subprocess.TimeoutExpired:
        return False, f"{argv[0]} did not finish within {COMMAND_TIMEOUT_S}s"
    except (OSError, subprocess.SubprocessError) as err:
        return False, f"{argv[0]} could not be run ({type(err).__name__})"
    if proc.returncode != 0:
        return False, (f"{argv[0]} exited {proc.returncode}: "
                       f"{one_line(proc.stderr or proc.stdout, 200)}")
    return True, ""


# ── what the caller uses ─────────────────────────────────────────────────────

# ── back to the terminal the work was started from ───────────────────────────
#
# WHY THIS CHANNEL EXISTS SEPARATELY. A toast goes to whoever is at this machine's
# desktop. It does not go to the session that actually asked for the work, and that
# session is the one holding the context - it knows what the run was for and can act on
# the answer. When a run stops at the operator gate, the person who started it is the
# person who has to look.
#
# WHAT "NON-BLOCKING" MEANS HERE, AND WHY IT IS A HARD RULE. There is an obvious
# mechanism for reaching a terminal that already has a session in it - `tmux send-keys`
# - and it is forbidden. Sending keys types into whatever is reading stdin: an agent's
# prompt, a half-finished command, a confirmation dialog waiting for y/n. That is not a
# notification, it is remote input, and pointing it at an LLM's prompt makes any text
# in a verdict into an instruction. Every route below either draws somewhere the
# terminal is not reading from (tmux's status line) or writes a file the recipient
# chooses when to read.

def origin_id():
    """A stable name for the terminal that is running this command.

    An agent pane knows its own name. Anything else - a person at a shell, a Claude
    Code session - is identified by its tmux pane if it has one, and otherwise is just
    the orchestrator, which is the identity the inbox already uses.
    """
    agent = os.environ.get("AGENTMUX_AGENT")
    if agent:
        return agent
    pane = os.environ.get("TMUX_PANE")
    if pane and pane.startswith("%") and pane[1:].isdigit():
        return f"pane{pane[1:]}"
    return "orchestrator"


def tmux_status(target, subject, socket="agentmux"):
    """Draw one line on a pane's STATUS BAR. Returns (ok, reason).

    display-message, never send-keys: the status line is chrome the pane is not reading
    from, so this cannot become input to whatever is running there. It is transient by
    design - the durable copy is the inbox entry written alongside it.
    """
    if not target:
        return False, "no pane to draw on"

    # THE TARGET IS CHECKED FIRST, AND THAT IS NOT BELT-AND-BRACES.
    #
    # `display-message -t <anything>` exits 0 whether or not the target resolves -
    # measured: a pane id that does not exist, and a plain string that is not an id at
    # all, both return 0 and draw nothing. So trusting its exit code reported a
    # notification as DELIVERED when it had gone nowhere, which is the one outcome this
    # whole module exists to prevent. `list-panes -t` is the command that actually
    # refuses an unknown target ("can't find pane: %999"), so resolution is asked of it
    # and the draw only happens once the pane is known to exist.
    try:
        check = subprocess.run(
            ["tmux", "-L", socket, "list-panes", "-t", target, "-F", "#{pane_id}"],
            capture_output=True, text=True, timeout=10, errors="replace")
    except (OSError, subprocess.SubprocessError) as err:
        return False, f"tmux could not be reached ({type(err).__name__})"
    if check.returncode != 0 or not (check.stdout or "").strip():
        return False, one_line(check.stderr or f"no such pane: {target}", 160)

    try:
        proc = subprocess.run(
            ["tmux", "-L", socket, "display-message", "-t", target, "--",
             one_line(f"agentmux: {subject}", 160)],
            capture_output=True, text=True, timeout=10, errors="replace")
    except (OSError, subprocess.SubprocessError) as err:
        return False, f"tmux could not be reached ({type(err).__name__})"
    if proc.returncode != 0:
        return False, one_line(proc.stderr or "tmux refused the target", 160)
    return True, ""


def deliver(subject, body, urgency="info", ref=None, toast_enabled=True,
            command="", pane=None):
    """Try every configured channel. Never raises, never blocks indefinitely.

    Returns a list of {channel, ok, reason}. An EMPTY list means nothing was configured
    at all, which the caller should treat differently from "everything failed" - the
    first is a choice and the second is a fault.

    Every channel is attempted even if an earlier one worked. They are different people
    at different desks, not a failover chain: a toast on this machine does nothing for
    someone who has gone home, which is exactly when the command hook matters.
    """
    out = []
    if toast_enabled:
        ok, reason = toast(subject, body, urgency)
        # No desktop is not a failure, it is a fact about the box. Reporting it as one
        # would make every plant-box run print a warning about a channel nobody asked
        # for, and warnings that are always there stop being read.
        if ok or "no desktop" not in reason:
            out.append({"channel": "desktop", "ok": ok, "reason": reason})
    if pane:
        ok, reason = tmux_status(pane, subject)
        out.append({"channel": "terminal", "ok": ok, "reason": reason})
    if command and str(command).strip():
        ok, reason = run_command(command, subject, body, urgency, ref)
        out.append({"channel": "command", "ok": ok, "reason": reason})
    return out


def main(argv=None):
    """`python3 taskmgmt/notify.py "subject" "body"` - so the channel can be tested
    without waiting for a run to escalate. A notification path nobody has ever fired is
    a notification path nobody knows is broken."""
    import argparse
    parser = argparse.ArgumentParser(description="send a test notification")
    parser.add_argument("subject")
    parser.add_argument("body", nargs="?", default="")
    parser.add_argument("--urgency", choices=("info", "warn", "error"), default="info")
    parser.add_argument("--command", default=os.environ.get("AGENTMUX_NOTIFY_COMMAND", ""))
    parser.add_argument("--no-toast", action="store_true")
    parser.add_argument("--pane", default=None,
                        help="tmux pane to draw a status line on")
    args = parser.parse_args(argv)
    results = deliver(args.subject, args.body, args.urgency,
                      toast_enabled=not args.no_toast, command=args.command,
                      pane=args.pane or os.environ.get("TMUX_PANE"))
    if not results:
        print("no channel is configured - nothing was sent", file=sys.stderr)
        return 1
    bad = 0
    for row in results:
        state = "ok" if row["ok"] else f"FAILED - {row['reason']}"
        print(f"  {row['channel']:<8} {state}")
        bad += 0 if row["ok"] else 1
    return 1 if bad == len(results) else 0


if __name__ == "__main__":
    sys.exit(main())
