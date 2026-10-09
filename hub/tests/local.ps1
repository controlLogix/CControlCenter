# Forward arguments without shell interpolation. Reuse the existing WSL tool cache.
$ErrorActionPreference = 'Stop'
$repoPath = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$linuxRoot = & wsl.exe --exec wslpath -a $repoPath
if ($LASTEXITCODE -ne 0) { throw 'Could not resolve the repository in the default WSL distribution.' }
$linuxRoot = $linuxRoot.Trim()
& wsl.exe --cd $linuxRoot --exec bash -c 'set -eu; cache="$HOME/.cache/agentmux-governance"; export PATH="$cache/tools:$PATH"; py="${AGENTMUX_TEST_PYTHON:-}"; if [ -z "$py" ]; then if [ -x .venv/bin/python ]; then py=.venv/bin/python; elif [ -x "$cache/venv/bin/python" ]; then py="$cache/venv/bin/python"; else py=python3; fi; fi; exec "$py" -m hub.tests.run_local "$@"' agentmux-tests @args
exit $LASTEXITCODE
