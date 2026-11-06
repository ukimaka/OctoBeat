; OctoBeat - музыкальный плеер
; Copyright (C) 2026 ukimaka
;
; Скрипт Inno Setup для Windows-установщика.
; Собирает готовую onedir-папку dist\OctoBeat, создаёт ярлыки на рабочем
; столе и в меню «Пуск», добавляет деинсталлятор и иконку приложения.
;
; Сборка (из корня репозитория, после pyinstaller OctoBeat.spec):
;   iscc installer.iss
;
; Версию можно переопределить из CI:
;   iscc /DMyAppVersion=1.2.3 installer.iss

#ifndef MyAppVersion
  #define MyAppVersion "1.0.0"
#endif

#ifndef MyAppNumericVersion
  #define MyAppNumericVersion "1.0.0.0"
#endif

#define MyAppName "OctoBeat"
#define MyAppPublisher "ukimaka"
#define MyAppURL "https://github.com/ukimaka/OctoBeat"
#define MyAppExeName "OctoBeat.exe"

[Setup]
; Устойчивый AppId: не меняйте его между версиями, иначе Windows будет
; считать каждую сборку новым приложением.
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

LicenseFile=LICENSE
OutputDir=installer_output
OutputBaseFilename=OctoBeat_Setup
SetupIconFile=icons\icon.ico
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
; PyInstaller onedir: OctoBeat.exe + _internal\ (Qt, VLC, Python, плагины).
Source: "dist\OctoBeat\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
