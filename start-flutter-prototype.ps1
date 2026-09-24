$ErrorActionPreference = 'Stop'
$application = Join-Path $PSScriptRoot 'dist\xinyu-flutter\windows\xinyu_flutter.exe'
if (-not (Test-Path -LiteralPath $application)) {
    throw 'Build first: clients\xinyu_flutter\tool\build.ps1 -Target windows -FlutterSdk <Flutter SDK path>'
}
# This is the visible, interactive application requested by the user.
Start-Process -FilePath $application -WorkingDirectory (Split-Path -Parent $application)
