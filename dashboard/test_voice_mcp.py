"""Gate entry for the voice-cli plugin's MCP suite, which lives with the plugin.

Every suite run_tests.sh registers is a dashboard/test_* file, and that is load-bearing:
test_residue.sh proves the runner restores the operator's server by swapping each
dashboard/test_* for a stub. A suite registered by a path outside dashboard/ is not
swapped, runs for real inside that fixture, and fails the runner it was meant to prove.
"""
import runpy
import sys
from pathlib import Path

TARGET = Path(__file__).resolve().parents[1] / "plugins" / "voice-cli" / "tests" / "test_voice_mcp.py"
sys.argv[0] = str(TARGET)
runpy.run_path(str(TARGET), run_name="__main__")
