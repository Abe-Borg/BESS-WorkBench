; Inno Setup script. ISCC resolves paths relative to this file.

#define MyAppName "BESS WorkBench"
#define MyAppVersion "0.1.0"
#define MyAppPublisher "BESS WorkBench contributors"
#define MyAppExeName "BESS-WorkBench.exe"

[Setup]
AppId={{60336033-4F21-4A10-9C2E-001122334455}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\BESS WorkBench
DefaultGroupName=BESS WorkBench
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=BESS-WorkBench-Setup
Compression=lzma
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}

[Files]
Source: "..\dist\BESS-WorkBench.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\BESS WorkBench"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\BESS WorkBench"; Filename: "{app}\{#MyAppExeName}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch BESS WorkBench"; Flags: nowait postinstall skipifsilent
