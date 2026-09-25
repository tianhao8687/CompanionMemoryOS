; Build with ISCC /DBundleDirectory=<absolute bundle> /ODirectory this-file.iss.
; Installs for the current user and preserves the separate user data directory.
#ifndef BundleDirectory
  #error BundleDirectory must point to the complete XinYu application bundle
#endif
#ifndef AppVersion
  #define AppVersion "0.2.0"
#endif

[Setup]
AppId={{EF131C2B-CB1C-4F28-A916-DAB1B227A474}
AppName=心隅
AppVersion={#AppVersion}
AppPublisher=CompanionMemoryOS
DefaultDirName={localappdata}\Programs\XinYu
DefaultGroupName=心隅
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputBaseFilename=XinYu-Windows-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\xinyu_flutter.exe
CloseApplications=yes
RestartApplications=no
LicenseFile={#BundleDirectory}\LICENSE

[Files]
Source: "{#BundleDirectory}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; Flags: unchecked

[Icons]
Name: "{autoprograms}\心隅"; Filename: "{app}\xinyu_flutter.exe"
Name: "{autodesktop}\心隅"; Filename: "{app}\xinyu_flutter.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\xinyu_flutter.exe"; Description: "打开心隅"; Flags: nowait postinstall skipifsilent
