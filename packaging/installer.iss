; Voice CLI installer (Inno Setup 6). Per-user: no administrator rights needed.
;   ISCC /DAppVersion=1.0.0 packaging\installer.iss      (build.ps1 does this)
; Silent deployment: VoiceCLI-Setup-<ver>.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART
;   add /TASKS="startup" to skip the desktop shortcut, or /TASKS="" for neither.
; Silent uninstall: "%LOCALAPPDATA%\Programs\VoiceCLI\unins000.exe" /VERYSILENT

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#define AppName "Voice CLI"
#define AppExe "VoiceCLI.exe"
; Must match APP_ID in src/voicecli/cli.py.
#define AppUserModelID "VoiceCLI.App"
#define RunKey "Software\Microsoft\Windows\CurrentVersion\Run"
#define ApprovedKey "Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run"

[Setup]
AppId={{C947F242-DE73-4E96-A56C-33EF617BC268}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppName}
VersionInfoVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\VoiceCLI
DisableDirPage=auto
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
OutputDir=..\dist
OutputBaseFilename=VoiceCLI-Setup-{#AppVersion}
SetupIconFile=..\assets\voicecli.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
WizardStyle=modern
; The Whisper weights barely compress, so favour a quick build over a slightly smaller file.
Compression=lzma2/fast
SolidCompression=no
LZMANumBlockThreads=4
CloseApplications=yes
RestartApplications=no
#ifdef Sign
SignTool=voicecli
SignedUninstaller=yes
#endif

[Tasks]
Name: "startup"; Description: "Start {#AppName} when I sign in to Windows"
Name: "desktopicon"; Description: "Create a desktop shortcut"

[InstallDelete]
; Runtime files from an older version must not mix with the new ones.
Type: filesandordirs; Name: "{app}\_internal"
; Shortcuts from the pre-1.0 source install (pythonw -m voicecli).
Type: files; Name: "{userdesktop}\{#AppName}.lnk"
Type: files; Name: "{userprograms}\{#AppName}.lnk"

[Files]
Source: "..\dist\VoiceCLI\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{userprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"; AppUserModelID: "{#AppUserModelID}"; Comment: "Talk to any CLI: push-to-talk, local Whisper"
Name: "{userdesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; AppUserModelID: "{#AppUserModelID}"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "{#RunKey}"; ValueType: string; ValueName: "VoiceCLI"; ValueData: """{app}\{#AppExe}"" --startup"; Tasks: startup; Flags: uninsdeletevalue
; Clears a "Disabled" flag left by Task Manager's Startup tab, so the ticked box really means on.
Root: HKCU; Subkey: "{#ApprovedKey}"; ValueType: binary; ValueName: "VoiceCLI"; ValueData: "02 00 00 00 00 00 00 00 00 00 00 00"; Tasks: startup; Flags: uninsdeletevalue

[Run]
Filename: "{app}\{#AppExe}"; Description: "Start {#AppName} now"; Flags: nowait postinstall

[UninstallRun]
Filename: "{app}\{#AppExe}"; Parameters: "--quit"; Flags: runhidden waituntilterminated; RunOnceId: "QuitVoiceCLI"

[Code]
procedure QuitRunningApp();
var
  Exe: String;
  Code: Integer;
begin
  { Ask a running Voice CLI to exit (it listens for this), so its files can be replaced. }
  Exe := ExpandConstant('{app}\{#AppExe}');
  if FileExists(Exe) then
    Exec(Exe, '--quit', '', SW_HIDE, ewWaitUntilTerminated, Code);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  QuitRunningApp();
  Result := '';
end;

procedure RemoveStartup();
begin
  RegDeleteValue(HKCU, '{#RunKey}', 'VoiceCLI');
  RegDeleteValue(HKCU, '{#ApprovedKey}', 'VoiceCLI');
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  { Unticking "start when I sign in" on an upgrade removes the entry an older install made. }
  if (CurStep = ssPostInstall) and not WizardIsTaskSelected('startup') then
    RemoveStartup();
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  { The app's own "Start with Windows" toggle may have written the entry too. }
  if CurUninstallStep = usUninstall then
    RemoveStartup();
end;
