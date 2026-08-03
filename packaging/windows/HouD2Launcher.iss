#ifndef MyAppVersion
  #define MyAppVersion GetEnv("HOUD2_BUILD_VERSION")
#endif
#ifndef MySourceDir
  #define MySourceDir GetEnv("HOUD2_BUILD_SOURCE")
#endif
#ifndef MyOutputDir
  #define MyOutputDir GetEnv("HOUD2_BUILD_OUTPUT")
#endif
#ifndef MyIconPath
  #define MyIconPath GetEnv("HOUD2_BUILD_ICON")
#endif

[Setup]
AppId={{7C7E8FB9-0A73-49B1-A135-B7E109DF8D42}
AppName=HouD2Launcher
AppVersion={#MyAppVersion}
AppPublisher=HouD2
DefaultDirName={localappdata}\Programs\HouD2Launcher
DefaultGroupName=HouD2Launcher
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#MyOutputDir}
OutputBaseFilename=HouD2Launcher-{#MyAppVersion}-Setup
SetupIconFile={#MyIconPath}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
UninstallDisplayIcon={app}\HouD2Launcher.exe

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "japanese"; MessagesFile: "compiler:Languages\Japanese.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a Desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: unchecked
Name: "dbadmin"; Description: "Create the Supervisor DB Admin shortcut"; GroupDescription: "Supervisor tools:"; Flags: unchecked

[Files]
Source: "{#MySourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\HouD2Launcher"; Filename: "{app}\HouD2Launcher.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\HouD2Launcher"; Filename: "{app}\HouD2Launcher.exe"; WorkingDir: "{app}"; Tasks: desktopicon
Name: "{group}\HouD2 DB Admin"; Filename: "{app}\HouD2Launcher.exe"; Parameters: "--db-admin"; WorkingDir: "{app}"; Tasks: dbadmin

[Run]
Filename: "{app}\HouD2Launcher.exe"; Description: "Launch HouD2Launcher"; Flags: nowait postinstall skipifsilent
