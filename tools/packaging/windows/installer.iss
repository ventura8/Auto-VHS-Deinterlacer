; Inno Setup Script for Auto-VHS-Deinterlacer
; Builds Windows standalone installer executable (EXE)

#define MyAppName "Auto-VHS-Deinterlacer"
#ifndef MyAppVersion
  #define MyAppVersion "1.1.0"
#endif
#define MyAppPublisher "Sergiu Alexandrescu"
#define MyAppURL "https://github.com/ventura8/Auto-VHS-Deinterlacer"
#define MyAppExeName "start.bat"

[Setup]
AppId={{C8E2613D-88F4-47B2-B647-380D4122C394}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DisableProgramGroupPage=yes
LicenseFile=..\..\..\LICENSE
OutputDir=..\..\..\dist
OutputBaseFilename=Auto-VHS-Deinterlacer-v{#MyAppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\..\..\auto_deinterlancer.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\..\start.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\..\config.yaml"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\..\install.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\..\pyproject.toml"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\..\poetry.lock"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\..\modules\*"; DestDir: "{app}\modules"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\..\..\assets\*"; DestDir: "{app}\assets"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "powershell.exe"; Parameters: "-ExecutionPolicy Bypass -File ""{app}\install.ps1"" -NoPause"; Description: "Run environment setup (install dependencies)"; Flags: postinstall runhidden
