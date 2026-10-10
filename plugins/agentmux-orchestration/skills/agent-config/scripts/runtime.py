"""Forward a supported command to an explicitly selected, trusted installation."""
import os
from pathlib import Path
import subprocess
import sys

COMMANDS = {"coordination": "coordination.py", "dispatch": "dispatch.py", "setup-auth": "setup_auth.py"}

def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] not in COMMANDS:
        print("expected coordination, dispatch, or setup-auth", file=sys.stderr)
        return 2
    binding = os.environ.get("AGENTMUX_REPO", "")
    root = Path(binding)
    if not binding or not root.is_absolute():
        print("AGENTMUX_REPO must name an absolute installed agentmux checkout", file=sys.stderr)
        return 2
    command = root / "taskmgmt" / COMMANDS[args[0]]
    if not command.is_file():
        print("missing installed command: " + str(command), file=sys.stderr)
        return 2
    try:
        return subprocess.run([sys.executable, str(command), *args[1:]], check=False).returncode
    except OSError as error:
        print("cannot start installed command: " + str(error), file=sys.stderr)
        return 2

if __name__ == "__main__":
    sys.exit(main())
