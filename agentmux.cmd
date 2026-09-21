@echo off
setlocal enabledelayedexpansion
REM agentmux - Windows entry point. Forwards to the WSL harness.
REM
REM Backslashes do not survive the Windows -> wsl.exe argv hand-off reliably,
REM so each argument is re-quoted here, and any argument that looks like a
REM drive-letter path (C:\foo) is rewritten to forward slashes (C:/foo).
REM Both Windows and the harness accept either form. Non-path arguments pass
REM through untouched, so prompt text keeps its backslashes.
REM
REM   agentmux spawn rev --cli codex --cwd C:\path\to\repo
REM   agentmux ask rev "what does modbus-forge do?"
REM   agentmux attach rev

set "OUT="
:loop
if "%~1"=="" goto run
set "A=%~1"
echo(!A!| findstr /r /c:"^[A-Za-z]:[\\/]" >nul && set "A=!A:\=/!"
set "OUT=!OUT! "!A!""
shift
goto loop

:run
REM OUT holds embedded quotes, so test with "if defined" - a string compare
REM against %OUT% would break batch parsing.
if defined OUT goto withargs
wsl.exe -d Ubuntu -- /home/nick/.local/bin/agentmux
goto done
:withargs
wsl.exe -d Ubuntu -- /home/nick/.local/bin/agentmux !OUT!
:done
endlocal
