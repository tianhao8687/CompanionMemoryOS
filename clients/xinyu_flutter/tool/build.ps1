param(
    [ValidateSet('windows', 'android', 'test', 'profile')][string]$Target = 'windows',
    [string]$FlutterSdk = $env:FLUTTER_ROOT,
    [string]$AndroidSdk = $env:ANDROID_HOME,
    [string]$JavaDirectory = $env:JAVA_HOME,
    [string]$BuildDirectory = (Join-Path $env:LOCALAPPDATA 'XinYuPrototype\build')
)
$ErrorActionPreference = 'Stop'
if ($Target -in @('windows', 'android')) {
    throw 'Standalone application builds now use tool/build_local.ps1, which includes the local engine. See README.md.'
}
$sourceDirectory = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$repositoryDirectory = [IO.Path]::GetFullPath((Join-Path $sourceDirectory '..\..'))
if ($FlutterSdk) { $flutterCommand = Join-Path $FlutterSdk 'bin\flutter.bat' }
else { $flutterCommand = (Get-Command flutter -ErrorAction Stop).Source }
if (-not (Test-Path -LiteralPath $flutterCommand)) { throw 'Flutter SDK not found. Pass -FlutterSdk.' }
$resolvedBuildDirectory = [IO.Path]::GetFullPath($BuildDirectory)
if ($resolvedBuildDirectory -match '[^\x00-\x7F]') { throw 'Choose an ASCII -BuildDirectory for the Windows/Android build tools.' }
if ($resolvedBuildDirectory.TrimEnd('\') -eq $sourceDirectory.TrimEnd('\')) { throw 'BuildDirectory must be separate from source.' }
New-Item -ItemType Directory -Path $resolvedBuildDirectory -Force | Out-Null
# Copy only; never mirror-delete files in either source or the build directory.
& robocopy $sourceDirectory $resolvedBuildDirectory /E /XD .dart_tool build .git ephemeral /XF local.properties .flutter-plugins-dependencies GeneratedPluginRegistrant.java Generated.xcconfig flutter_export_environment.sh generated_plugin_registrant.cc generated_plugin_registrant.h generated_plugins.cmake /NFL /NDL /NJH /NJS
if ($LASTEXITCODE -gt 7) { throw "Source copy failed: $LASTEXITCODE" }
if ($AndroidSdk) { $env:ANDROID_HOME = $AndroidSdk }
if ($JavaDirectory) { $env:JAVA_HOME = $JavaDirectory }
Push-Location -LiteralPath $resolvedBuildDirectory
try {
    & $flutterCommand pub get
    if ($LASTEXITCODE -ne 0) { throw 'Dependency resolution failed.' }
    switch ($Target) {
        'test' {
            & $flutterCommand analyze
            if ($LASTEXITCODE -ne 0) { throw 'Static analysis failed.' }
            & $flutterCommand test
        }
        'profile' {
            $env:XINYU_MAXIMIZED = '1'
            & $flutterCommand drive --profile -d windows --driver=test_driver/integration_test.dart --target=integration_test/glass_performance_test.dart
        }
        'windows' { & $flutterCommand build windows --release }
        'android' { & $flutterCommand build apk --release }
    }
    if ($LASTEXITCODE -ne 0) { throw "Flutter $Target failed." }
    $deliveryDirectory = Join-Path $repositoryDirectory 'dist\xinyu-flutter'
    if ($Target -eq 'windows') {
        $windowsOutput = Join-Path $deliveryDirectory 'windows'
        New-Item -ItemType Directory -Path $windowsOutput -Force | Out-Null
        & robocopy (Join-Path $resolvedBuildDirectory 'build\windows\x64\runner\Release') $windowsOutput /E /NFL /NDL /NJH /NJS
        if ($LASTEXITCODE -gt 7) { throw 'Packaging Windows output failed.' }
        Write-Host (Join-Path $windowsOutput 'xinyu_flutter.exe')
    }
    if ($Target -eq 'android') {
        New-Item -ItemType Directory -Path $deliveryDirectory -Force | Out-Null
        Copy-Item -LiteralPath (Join-Path $resolvedBuildDirectory 'build\app\outputs\flutter-apk\app-release.apk') -Destination (Join-Path $deliveryDirectory 'xinyu-prototype.apk')
        Write-Host (Join-Path $deliveryDirectory 'xinyu-prototype.apk')
    }
} finally { Pop-Location }
