; Inno Setup script for Roundtable Hold (Windows).
;   iscc /DAppVersion=0.3.0 packaging\installer.iss
; Installs per-user (no admin prompt) into %LOCALAPPDATA%\Programs\Roundtable Hold.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{6C3E4E2A-6F3B-4C55-9F7E-52B1D1A0C0DE}
AppName=Roundtable Hold
AppVersion={#AppVersion}
AppVerName=Roundtable Hold {#AppVersion}
AppPublisher=MEZTKING
AppPublisherURL=https://github.com/MEZTKING/agent-harness
AppUpdatesURL=https://github.com/MEZTKING/agent-harness/releases
DefaultDirName={localappdata}\Programs\Roundtable Hold
DefaultGroupName=Roundtable Hold
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=RoundtableHold-Setup-{#AppVersion}
SetupIconFile=roundtable.ico
UninstallDisplayIcon={app}\RoundtableHold.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=yes

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "..\dist\RoundtableHold\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Roundtable Hold"; Filename: "{app}\RoundtableHold.exe"
Name: "{autodesktop}\Roundtable Hold"; Filename: "{app}\RoundtableHold.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\RoundtableHold.exe"; Description: "Open Roundtable Hold"; Flags: nowait postinstall skipifsilent
; after a silent in-app update, reopen the app (pass /NOLAUNCH=1 to skip, e.g. in CI)
Filename: "{app}\RoundtableHold.exe"; Flags: nowait; Check: ShouldRelaunch

[Code]
function ShouldRelaunch: Boolean;
begin
  Result := WizardSilent and (ExpandConstant('{param:NOLAUNCH|0}') = '0');
end;

; Your projects, journal, settings and keys are kept on uninstall
; (%APPDATA%\RoundtableHold and Windows Credential Manager).
