# compat/

GNU/util-linux commands the repo's scripts use that macOS does not ship: `flock`,
`timeout`, `setsid`, `tac`. Scripts prepend `compat/bin` to `PATH` **only on macOS**
(`uname -s` = Darwin), so a Linux or WSL box keeps running the real tools.

`agentmux.sh` does not use this directory. Suites copy it alone into fixture
directories, so it carries its own equivalent shims inline.
