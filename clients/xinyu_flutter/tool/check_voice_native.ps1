param(
    [Parameter(Mandatory=$true)][string]$Output,
    [string]$AndroidSdk = 'C:/Users/Admin/.cache/chu-men-bie-wang-android/sdk',
    [string]$JavaDirectory = 'C:/Users/Admin/.cache/chu-men-bie-wang-android/jdk21/jdk-21.0.12+8',
    [string]$FlutterSdk = $env:FLUTTER_ROOT,
    [switch]$Offline
)
$ErrorActionPreference = 'Stop'
$client = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$stage = [IO.Path]::GetFullPath((Join-Path $Output 'voice-native'))
if ($stage -match '[^\x00-\x7F]') { throw 'Use an ASCII output path for Gradle.' }
New-Item -ItemType Directory -Path $stage -Force | Out-Null
$plugins = Get-Content (Join-Path $client '.flutter-plugins-dependencies') -Raw | ConvertFrom-Json
foreach ($module in @('record_android', 'sherpa_onnx_android')) {
    $plugin = $plugins.plugins.android | Where-Object name -eq $module | Select-Object -First 1
    if (-not $plugin) { throw "Run flutter pub get first: $module is missing." }
    & robocopy (Join-Path $plugin.path 'android') (Join-Path $stage $module) /E /XD build .gradle .kotlin /NFL /NDL /NJH /NJS /NP /R:1 /W:1
    if ($LASTEXITCODE -ge 8) { throw 'Plugin staging failed.' }
}
Copy-Item -LiteralPath (Join-Path $client 'android/gradlew.bat') -Destination $stage
Copy-Item -LiteralPath (Join-Path $client 'android/gradle') -Destination $stage -Recurse -Force
$engine = (Get-Content (Join-Path $FlutterSdk 'bin/cache/engine.stamp') -Raw).Trim()
# Original plugin build scripts and source, with the same Flutter embedding used by
# the app. Only Android library compile/AAR tasks: this project cannot produce an APK.
@'
pluginManagement { repositories { google(); mavenCentral(); gradlePluginPortal() } }
plugins { id("com.android.library") version "9.1.0" apply false }
rootProject.name = "XinYuVoicePluginChecks"
include(":record_android", ":sherpa_onnx_android")
'@ | Set-Content (Join-Path $stage 'settings.gradle.kts') -Encoding utf8
@'
subprojects {
    ext.flutter = [compileSdkVersion: 36, ndkVersion: "28.2.13676358"]
    repositories { google(); mavenCentral(); maven { url "https://storage.googleapis.com/download.flutter.io" } }
    plugins.withId("com.android.library") {
        dependencies.add("implementation", "io.flutter:flutter_embedding_debug:1.0.0-ENGINE_HASH")
    }
}
'@.Replace('ENGINE_HASH', $engine) | Set-Content (Join-Path $stage 'build.gradle') -Encoding utf8
('sdk.dir=' + $AndroidSdk.Replace('\','/')) | Set-Content (Join-Path $stage 'local.properties') -Encoding utf8
@'
org.gradle.jvmargs=-Xmx1536m -Dfile.encoding=UTF-8
android.useAndroidX=true
'@ | Set-Content (Join-Path $stage 'gradle.properties') -Encoding utf8
$env:JAVA_HOME = $JavaDirectory
$arguments = @(':record_android:compileDebugKotlin', ':sherpa_onnx_android:assembleDebug', '--no-daemon', '--console=plain')
if ($Offline) { $arguments += '--offline' }
Push-Location $stage
try {
    & ./gradlew.bat @arguments *> (Join-Path $Output 'voice-native.log')
    $checkExit = $LASTEXITCODE
} finally { Pop-Location }
Get-Content (Join-Path $Output 'voice-native.log') -Tail 45
exit $checkExit
