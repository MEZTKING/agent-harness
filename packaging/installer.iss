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

; Your projects, journal, settings and keys are kept on uninstall
; (%APPDATA%\RoundtableHold and Windows Credential Manager).

; The phone connects to this PC (TCP 8766) and finds it on the Wi-Fi (UDP 8767). Two firewall rules let those
; in on private networks only, for RoundtableHold.exe only, so Windows doesn't ask when the phone first connects.
; Adding a rule needs administrator rights and this installer runs without them, so a normal install asks once
; (one Windows "Yes"), only when the rules aren't there yet; silent updates and CI never ask. Uninstall removes them.

[Code]
// Pascal Script: comments here use // not ;
const
  FwPhone = 'Roundtable Hold - phone (TCP 8766)';
  FwFind = 'Roundtable Hold - finding this PC (UDP 8767)';

function ShouldRelaunch: Boolean;
begin
  Result := WizardSilent and (ExpandConstant('{param:NOLAUNCH|0}') = '0');
end;

// "show rule" works without administrator rights: 0 when a rule with that name exists
function RuleThere(const Name: String): Boolean;
var
  Code: Integer;
begin
  Result := Exec(ExpandConstant('{sys}\netsh.exe'), 'advfirewall firewall show rule name="' + Name + '"', '',
    SW_HIDE, ewWaitUntilTerminated, Code) and (Code = 0);
end;

// one script run as administrator: one Windows prompt for both rules
function RunElevated(const Lines: String): Boolean;
var
  Script: String;
  Code: Integer;
begin
  Script := AddBackslash(GetTempDir) + 'roundtable-firewall.cmd';
  Result := SaveStringToFile(Script, '@echo off' + #13#10 + Lines, False) and
    ShellExec('runas', Script, '', '', SW_HIDE, ewWaitUntilTerminated, Code);
  DeleteFile(Script);
end;

function DeleteLines: String;
begin
  Result := 'netsh advfirewall firewall delete rule name="' + FwPhone + '" >nul 2>&1' + #13#10 +
    'netsh advfirewall firewall delete rule name="' + FwFind + '" >nul 2>&1' + #13#10;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Exe: String;
begin
  if (CurStep <> ssPostInstall) or WizardSilent then
    Exit;
  if RuleThere(FwPhone) and RuleThere(FwFind) then
    Exit;
  Exe := ExpandConstant('{app}\RoundtableHold.exe');
  if not RunElevated(DeleteLines +
      'netsh advfirewall firewall add rule name="' + FwPhone + '" dir=in action=allow protocol=TCP localport=8766 profile=private program="' + Exe + '"' + #13#10 +
      'netsh advfirewall firewall add rule name="' + FwFind + '" dir=in action=allow protocol=UDP localport=8767 profile=private program="' + Exe + '"' + #13#10) then
    Log('The firewall rules for the phone were not added (the Windows prompt was refused): Windows will ask when the phone first connects.');
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if (CurUninstallStep <> usUninstall) or UninstallSilent then
    Exit;
  if RuleThere(FwPhone) or RuleThere(FwFind) then
    RunElevated(DeleteLines);
end;
