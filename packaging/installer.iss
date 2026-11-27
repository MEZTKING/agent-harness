; Inno Setup script for Darkness Harness (Windows), called Roundtable Hold before 1.0.0.
;   iscc /DAppVersion=1.0.0 packaging\installer.iss
; Installs per-user (no admin prompt) into %LOCALAPPDATA%\Programs\Darkness Harness.
;
; Upgrading from Roundtable Hold: the AppId below is the one Roundtable Hold always had, so this installs
; over it (never beside it). Inno then keeps the folder it was in (%LOCALAPPDATA%\Programs\Roundtable Hold):
; nobody sees it, so it stays. [InstallDelete] clears the old shortcuts, and RoundtableHold.exe is replaced
; by a small starter that opens DarknessHarness.exe, so a taskbar pin made by hand keeps working.
; The data folder (%APPDATA%\RoundtableHold) and the keys are never touched: the app keeps using them.
; NEVER change the AppId (tests/test_passage.py checks it).

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#define AppName "Darkness Harness"
#define AppExe "DarknessHarness.exe"
#define LegacyName "Roundtable Hold"
#define LegacyExe "RoundtableHold.exe"

[Setup]
AppId={{6C3E4E2A-6F3B-4C55-9F7E-52B1D1A0C0DE}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=MEZTKING
AppPublisherURL=https://github.com/MEZTKING/agent-harness
AppUpdatesURL=https://github.com/MEZTKING/agent-harness/releases
DefaultDirName={localappdata}\Programs\{#AppName}
; an upgrade keeps the old install folder (UsePreviousAppDir, Inno's default) but not the old Start menu
; folder: the new shortcut goes in "Darkness Harness" and the old one is removed below
DefaultGroupName={#AppName}
UsePreviousGroup=no
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=DarknessHarness-Setup-{#AppVersion}
SetupIconFile=darkness.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=yes

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"

[InstallDelete]
; what Roundtable Hold left that would now be wrong (runs before the new files are copied; the old
; RoundtableHold.exe is then put back as the small starter by [Files])
Type: files; Name: "{app}\{#LegacyExe}"
Type: files; Name: "{autoprograms}\{#LegacyName}\{#LegacyName}.lnk"
Type: dirifempty; Name: "{autoprograms}\{#LegacyName}"
Type: files; Name: "{autoprograms}\{#LegacyName}.lnk"
Type: files; Name: "{autodesktop}\{#LegacyName}.lnk"

[Files]
Source: "..\dist\DarknessHarness\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "Open {#AppName}"; Flags: nowait postinstall skipifsilent
; after a silent in-app update, reopen the app (pass /NOLAUNCH=1 to skip, e.g. in CI)
Filename: "{app}\{#AppExe}"; Flags: nowait; Check: ShouldRelaunch

; Your projects, journal, settings and keys are kept on uninstall
; (%APPDATA%\DarknessHarness, or %APPDATA%\RoundtableHold on a PC that had Roundtable Hold, and Windows
; Credential Manager).

; The phone connects to this PC (TCP 8766) and finds it on the Wi-Fi (UDP 8767). Two firewall rules let those
; in on private networks only, for DarknessHarness.exe only, so Windows doesn't ask when the phone first connects.
; Adding a rule needs administrator rights and this installer runs without them, so a normal install asks once
; (one Windows "Yes"), only when the rules aren't there yet; silent updates and CI never ask, with one exception:
; the silent update from Roundtable Hold, when the owner had already said Yes to the old rules (they were for
; RoundtableHold.exe, so the phone would stop reaching the PC). Then it asks once, to move them to the new app.
; /NOFIREWALL=1 skips the firewall step altogether (CI). Uninstall removes the old rules and the new.

[Code]
// Pascal Script: comments here use // not ;
const
  FwPhone = 'Darkness Harness - phone (TCP 8766)';
  FwFind = 'Darkness Harness - finding this PC (UDP 8767)';
  OldFwPhone = 'Roundtable Hold - phone (TCP 8766)';
  OldFwFind = 'Roundtable Hold - finding this PC (UDP 8767)';

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
  Script := AddBackslash(GetTempDir) + 'darkness-firewall.cmd';
  Result := SaveStringToFile(Script, '@echo off' + #13#10 + Lines, False) and
    ShellExec('runas', Script, '', '', SW_HIDE, ewWaitUntilTerminated, Code);
  DeleteFile(Script);
end;

function DeleteLines: String;
begin
  Result := 'netsh advfirewall firewall delete rule name="' + FwPhone + '" >nul 2>&1' + #13#10 +
    'netsh advfirewall firewall delete rule name="' + FwFind + '" >nul 2>&1' + #13#10 +
    'netsh advfirewall firewall delete rule name="' + OldFwPhone + '" >nul 2>&1' + #13#10 +
    'netsh advfirewall firewall delete rule name="' + OldFwFind + '" >nul 2>&1' + #13#10;
end;

function SkipFirewall: Boolean;
begin
  Result := ExpandConstant('{param:NOFIREWALL|0}') <> '0';
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Exe: String;
begin
  if (CurStep <> ssPostInstall) or SkipFirewall then
    Exit;
  if RuleThere(FwPhone) and RuleThere(FwFind) then
    Exit;
  // silent: only the move from Roundtable Hold's rules, which the owner already agreed to once
  if WizardSilent and not (RuleThere(OldFwPhone) or RuleThere(OldFwFind)) then
    Exit;
  Exe := ExpandConstant('{app}\{#AppExe}');
  if not RunElevated(DeleteLines +
      'netsh advfirewall firewall add rule name="' + FwPhone + '" dir=in action=allow protocol=TCP localport=8766 profile=private program="' + Exe + '"' + #13#10 +
      'netsh advfirewall firewall add rule name="' + FwFind + '" dir=in action=allow protocol=UDP localport=8767 profile=private program="' + Exe + '"' + #13#10) then
    Log('The firewall rules for the phone were not added (the Windows prompt was refused): Windows will ask when the phone first connects.');
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if (CurUninstallStep <> usUninstall) or UninstallSilent then
    Exit;
  if RuleThere(FwPhone) or RuleThere(FwFind) or RuleThere(OldFwPhone) or RuleThere(OldFwFind) then
    RunElevated(DeleteLines);
end;
