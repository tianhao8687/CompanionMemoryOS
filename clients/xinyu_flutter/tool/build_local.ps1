param(
    [ValidateSet('windows', 'android', 'test')][string]$Target = 'windows',
    [string]$FlutterSdk = $env:FLUTTER_ROOT,
    [string]$AndroidSdk = $env:ANDROID_HOME,
    [string]$JavaDirectory = $env:JAVA_HOME,
    [string]$BuildPython = $env:XINYU_BUILD_PYTHON,
    [string]$AndroidWheels = $env:XINYU_ANDROID_WHEELS,
    [string]$BuildRoot = (Join-Path $env:LOCALAPPDATA 'XinYuBuild\releases')
)
$ErrorActionPreference = 'Stop'
$clientSource = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$repository = [IO.Path]::GetFullPath((Join-Path $clientSource '..\..'))
$python = Join-Path $repository '.venv\Scripts\python.exe'
if (-not $FlutterSdk) { $FlutterSdk = Join-Path $env:LOCALAPPDATA 'XinYuBuild\flutter' }
$flutter = Join-Path $FlutterSdk 'bin\flutter.bat'
if (-not (Test-Path -LiteralPath $flutter)) { throw 'Flutter SDK missing. Pass -FlutterSdk.' }
if (-not (Test-Path -LiteralPath $python)) { throw 'Project Python environment missing.' }
$runId = [guid]::NewGuid().ToString('N')
$run = [IO.Path]::GetFullPath((Join-Path $BuildRoot $runId))
if ($run -match '[^\x00-\x7F]') { throw 'BuildRoot must be an ASCII path for Flutter and Gradle.' }
$client = Join-Path $run 'client'
New-Item -ItemType Directory -Path $client -Force | Out-Null
& robocopy $clientSource $client /E /XD .git .dart_tool build ephemeral __pycache__ python wheels /XF local.properties .flutter-plugins-dependencies GeneratedPluginRegistrant.java generated_plugin_registrant.cc generated_plugin_registrant.h generated_plugins.cmake /NFL /NDL /NJH /NJS
if ($LASTEXITCODE -gt 7) { throw 'Client source copy failed.' }
if ($AndroidSdk) { $env:ANDROID_HOME = $AndroidSdk }
if ($JavaDirectory) { $env:JAVA_HOME = $JavaDirectory }
if ($BuildPython) { $env:XINYU_BUILD_PYTHON = $BuildPython }
if ($AndroidWheels) { $env:XINYU_ANDROID_WHEELS = [IO.Path]::GetFullPath($AndroidWheels) }

Push-Location -LiteralPath $client
try {
    & $flutter pub get
    if ($LASTEXITCODE) { throw 'Flutter dependency resolution failed.' }
    & $flutter analyze
    if ($LASTEXITCODE) { throw 'Flutter analysis failed.' }
    & $flutter test
    if ($LASTEXITCODE) { throw 'Flutter tests failed.' }
    if ($Target -eq 'test') { exit 0 }
    $delivery = Join-Path $repository ("dist\xinyu-local\" + $runId)
    New-Item -ItemType Directory -Path $delivery -Force | Out-Null
    if ($Target -eq 'windows') {
        & $flutter build windows --release
        if ($LASTEXITCODE) { throw 'Windows UI build failed; install the Visual Studio C++ desktop workload.' }
        & $python (Join-Path $PSScriptRoot 'package_windows_engine.py') --output (Join-Path $run 'engine-dist') --work (Join-Path $run 'engine-build')
        if ($LASTEXITCODE) { throw 'Windows engine packaging failed.' }
        $bundle = Join-Path $delivery 'XinYu'
        New-Item -ItemType Directory -Path $bundle -Force | Out-Null
        & robocopy (Join-Path $client 'build\windows\x64\runner\Release') $bundle /E /NFL /NDL /NJH /NJS
        if ($LASTEXITCODE -gt 7) { throw 'Windows UI packaging failed.' }
        & robocopy (Join-Path $run 'engine-dist\xinyu-engine') (Join-Path $bundle 'engine') /E /NFL /NDL /NJH /NJS
        if ($LASTEXITCODE -gt 7) { throw 'Windows engine copy failed.' }
        $vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
        $vsDirectory = & $vswhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
        if (-not $vsDirectory) { throw 'Cannot find the Microsoft C++ redistributable files.' }
        foreach ($name in @('msvcp140.dll', 'vcruntime140.dll', 'vcruntime140_1.dll')) {
            $runtime = Get-ChildItem -LiteralPath (Join-Path $vsDirectory 'VC\Redist\MSVC') -Filter $name -Recurse |
                Where-Object FullName -Match '\\x64\\Microsoft\.VC[^\\]+\.CRT\\' |
                Sort-Object FullName -Descending | Select-Object -First 1
            if (-not $runtime) { throw "Missing C++ runtime: $name" }
            Copy-Item -LiteralPath $runtime.FullName -Destination (Join-Path $bundle $name)
        }
        Copy-Item -LiteralPath (Join-Path $repository 'LICENSE') -Destination $bundle
        & $python (Join-Path $PSScriptRoot 'smoke_native_engine.py') --engine (Join-Path $bundle 'engine\xinyu-engine.exe')
        if ($LASTEXITCODE) { throw 'The packaged engine failed acceptance. Artifacts retained for diagnosis.' }
        Compress-Archive -LiteralPath $bundle -DestinationPath (Join-Path $delivery 'XinYu-Windows.zip')
    } else {
        if (-not $BuildPython) { throw 'Android packaging requires a Python 3.13 host. Pass -BuildPython.' }
        if (-not $AndroidWheels) { throw 'Android native wheels missing. Pass -AndroidWheels after building them.' }
        & $python (Join-Path $PSScriptRoot 'prepare_engine.py') --output (Join-Path $run 'android-engine')
        if ($LASTEXITCODE) { throw 'Engine staging failed.' }
        $env:XINYU_ENGINE_SOURCES = Join-Path $run 'android-engine\python'
        & $flutter build apk --release --target-platform android-arm64
        if ($LASTEXITCODE) { throw 'Android build failed. No independent APK has been delivered.' }
        Copy-Item -LiteralPath (Join-Path $client 'build\app\outputs\flutter-apk\app-release.apk') -Destination (Join-Path $delivery 'XinYu-Android-arm64.apk')
    }
    Get-ChildItem -LiteralPath $delivery -File | Get-FileHash -Algorithm SHA256
    Write-Output "Local application artifacts: $delivery"
} finally { Pop-Location }
