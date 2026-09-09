; Inno Setup 6 script — run build.bat (it calls ISCC after PyInstaller).
#define AppName "Aemyos"
#define AppVersion "1.8"
#define AppPublisher "Aemyos"
#define AppURL "https://aemyos.ai"
#define AppExe "Aemyos.exe"

[Setup]
AppId={{B7E1C4A2-6F3D-4B9A-8E21-0C5A9D7F3E18}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/contact.html
AppUpdatesURL={#AppURL}/download.html
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
; Per-user install (no UAC prompt): lands in %LOCALAPPDATA%\Programs\Aemyos.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=dist
OutputBaseFilename=Aemyos-Setup-{#AppVersion}
SetupIconFile=assets\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
CloseApplications=yes
RestartApplications=no
; build.bat passes /Saemyos="sign.bat $f"; without signing.json that is a no-op.
SignTool=aemyos
SignedUninstaller=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "turkish"; MessagesFile: "compiler:Languages\Turkish.isl"
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"
Name: "german"; MessagesFile: "compiler:Languages\German.isl"
Name: "french"; MessagesFile: "compiler:Languages\French.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "startup"; Description: "Start {#AppName} when Windows starts"; GroupDescription: "Startup:"; Flags: unchecked

[Files]
Source: "dist\Aemyos\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "{#AppName}"; ValueData: """{app}\{#AppExe}"""; Flags: uninsdeletevalue; Tasks: startup

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "taskkill"; Parameters: "/IM {#AppExe} /F"; Flags: runhidden; RunOnceId: "KillAemyos"

; User data (%APPDATA%\Aemyos: keys, memory, notes) is kept on uninstall on purpose.
