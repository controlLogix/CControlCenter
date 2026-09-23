<#
.SYNOPSIS
  Builds dist\VoiceCLI\ (the standalone app) and dist\VoiceCLI-Setup-<version>.exe (the installer).

.DESCRIPTION
  Needs uv and Inno Setup 6 (winget install JRSoftware.InnoSetup --scope user).
  Runs the tests, freezes the app with PyInstaller, adds the pinned and checksum-verified
  Whisper models, smoke-tests the exe, then compiles the installer.

  Code signing: set VOICECLI_SIGN_THUMBPRINT to the SHA-1 thumbprint of a code-signing
  certificate in your store (signtool.exe from the Windows SDK must be on PATH). The exe,
  the installer and the uninstaller are then signed and timestamped.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File packaging\build.ps1
#>
param(
    [switch]$SkipTests,
    [switch]$NoInstaller
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Invoke-Checked {
    param([string]$Exe, [string[]]$Arguments)
    # Windows PowerShell turns a native tool's stderr (uv and PyInstaller log there) into
    # terminating errors under "Stop"; the exit code is what decides success.
    $ErrorActionPreference = "Continue"
    & $Exe @Arguments 2>&1 | ForEach-Object { "$_" }
    if ($LASTEXITCODE -ne 0) { throw "$Exe $($Arguments -join ' ') failed with exit code $LASTEXITCODE" }
}

$sign = $env:VOICECLI_SIGN_THUMBPRINT
$timestamp = if ($env:VOICECLI_TIMESTAMP_URL) { $env:VOICECLI_TIMESTAMP_URL } else { "http://timestamp.digicert.com" }
function Sign-File([string]$Path) {
    if (-not $sign) { return }
    Invoke-Checked signtool @("sign", "/sha1", $sign, "/fd", "sha256", "/tr", $timestamp, "/td", "sha256", $Path)
}

Invoke-Checked uv @("sync", "--frozen", "--group", "dev", "--group", "build")
$version = (Invoke-Checked uv @("run", "--no-sync", "python", "-c", "import voicecli; print(voicecli.__version__)") |
            Select-Object -Last 1).Trim()
Write-Host "Voice CLI $version"

if (-not $SkipTests) {
    Invoke-Checked uv @("run", "--no-sync", "pytest")
}

Invoke-Checked uv @("run", "--no-sync", "pyinstaller", "packaging\voicecli.spec", "--noconfirm", "--clean",
                    "--distpath", "dist", "--workpath", "build\pyinstaller")
Invoke-Checked uv @("run", "--no-sync", "python", "packaging\fetch_models.py", "dist\VoiceCLI\models")
Sign-File "dist\VoiceCLI\VoiceCLI.exe"

# The frozen exe must load the bundled models offline and transcribe (details in the app log).
$p = Start-Process -FilePath "dist\VoiceCLI\VoiceCLI.exe" -ArgumentList "--self-test" -PassThru -Wait
if ($p.ExitCode -ne 0) { throw "VoiceCLI.exe --self-test failed (exit $($p.ExitCode)); see %LOCALAPPDATA%\voicecli\logs" }
Write-Host "dist\VoiceCLI\VoiceCLI.exe passes its self-test"

if (-not $NoInstaller) {
    $iscc = @(
        (Get-Command ISCC.exe -ErrorAction SilentlyContinue).Source,
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
    ) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
    if (-not $iscc) { throw "Inno Setup 6 not found: winget install JRSoftware.InnoSetup --scope user" }
    $isccArgs = @("/Qp", "/DAppVersion=$version")
    if ($sign) {
        $isccArgs += "/DSign"
        $isccArgs += "/Svoicecli=signtool sign /sha1 $sign /fd sha256 /tr $timestamp /td sha256 `$f"
    }
    Invoke-Checked $iscc ($isccArgs + "packaging\installer.iss")
    Write-Host "dist\VoiceCLI-Setup-$version.exe"
}
