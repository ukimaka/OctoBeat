; OctoBeat Windows installer.
; Built by .github/workflows/release.yml:
;   cmake --install ... --prefix dist\OctoBeat
;   iscc /DMyAppVersion=1.0.0 packaging\windows\OctoBeat.iss

#ifndef MyAppVersion
  #define MyAppVersion "1.0.0"
#endif
#ifndef MyAppNumericVersion
  #define MyAppNumericVersion "1.0.0.0"
#endif

#define MyAppName "OctoBeat"
#define MyAppPublisher "ukimaka"
#define MyAppURL "https://github.com/ukimaka/OctoBeat"
#define MyAppExeName "bin\octobeat.exe"

[Setup]
AppId={{92DE1FA7-C552-4025-B5CC-00782B8836F1}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues
AppUpdatesURL={#MyAppURL}/releases
AppCopyright=Copyright (C) 2026 {#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
AllowNoIcons=yes
LicenseFile=..\..\LICENSE
OutputDir=..\..\dist\installer
OutputBaseFilename=OctoBeat_Setup
SetupIconFile=..\..\icons\icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription={#MyAppName} installer
VersionInfoProductName={#MyAppName}
VersionInfoVersion={#MyAppNumericVersion}
VersionInfoProductVersion={#MyAppNumericVersion}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\..\dist\OctoBeat\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}\bin"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}\bin"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}\bin"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
