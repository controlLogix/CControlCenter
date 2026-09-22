# Creates "Voice CLI" shortcuts (Start menu + desktop) that start voicecli without a console.
# Launching one while voicecli is already running just brings its overlay forward.
# Pin to the taskbar: Start menu -> right-click "Voice CLI" -> Pin to taskbar.

$root = $PSScriptRoot
$pythonw = Join-Path $root ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $pythonw)) { Write-Error "Run 'uv sync' in $root first."; exit 1 }

$shell = New-Object -ComObject WScript.Shell
$places = @(
    [Environment]::GetFolderPath("Programs"),
    [Environment]::GetFolderPath("Desktop")
)
foreach ($dir in $places) {
    $lnk = $shell.CreateShortcut((Join-Path $dir "Voice CLI.lnk"))
    $lnk.TargetPath = $pythonw
    $lnk.Arguments = "-m voicecli"
    $lnk.WorkingDirectory = $root
    $lnk.IconLocation = (Join-Path $root "assets\voicecli.ico") + ",0"
    $lnk.Description = "Talk to any CLI (push-to-talk, local Whisper)"
    $lnk.Save()
    Write-Output "created $($lnk.FullName)"
}
