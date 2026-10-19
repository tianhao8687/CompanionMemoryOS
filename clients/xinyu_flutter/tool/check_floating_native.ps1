param(
    [Parameter(Mandatory=$true)][string]$Output,
    [string]$AndroidSdk = 'C:/Users/Admin/.cache/chu-men-bie-wang-android/sdk',
    [string]$JavaDirectory = 'C:/Users/Admin/.cache/chu-men-bie-wang-android/jdk21/jdk-21.0.12+8',
    [string]$FlutterSdk = $env:FLUTTER_ROOT,
    [string]$LogName = 'native-1.log'
)
$ErrorActionPreference = 'Stop'
$android = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../android'))
$stage = [IO.Path]::GetFullPath((Join-Path $Output 'native'))
if ($stage -match '[^\x00-\x7F]') { throw 'Use an ASCII output path for Gradle.' }
New-Item -ItemType Directory -Path $stage -Force | Out-Null
foreach ($module in @('droid_mcp', 'phone_bridge')) {
    & robocopy (Join-Path $android $module) (Join-Path $stage $module) /E /XD build .gradle .kotlin /NFL /NDL /NJH /NJS /NP /R:1 /W:1
    if ($LASTEXITCODE -ge 8) { throw 'Module staging failed.' }
}
Copy-Item -LiteralPath (Join-Path $android 'gradlew.bat') -Destination $stage
Copy-Item -LiteralPath (Join-Path $android 'gradle') -Destination $stage -Recurse -Force
$appCheck = Join-Path $stage 'app_check'
New-Item -ItemType Directory -Path (Join-Path $appCheck 'src/main') -Force | Out-Null
foreach ($directory in @('kotlin','res')) {
    & robocopy (Join-Path $android "app/src/main/$directory") (Join-Path $appCheck "src/main/$directory") /E /NFL /NDL /NJH /NJS /NP /R:1 /W:1
    if ($LASTEXITCODE -ge 8) { throw 'Application Kotlin staging failed.' }
}
# Compile the real Activity, bridge and runtime against the actual Flutter/Chaquopy SDKs.
# No application plugin, bundle or APK task is present in this check project.
'<manifest />' | Set-Content (Join-Path $appCheck 'src/main/AndroidManifest.xml') -Encoding utf8
$engine = (Get-Content (Join-Path $FlutterSdk 'bin/cache/engine.stamp') -Raw).Trim()
$gradleCache = if ($env:GRADLE_USER_HOME) { $env:GRADLE_USER_HOME } else { Join-Path $env:USERPROFILE '.gradle' }
$pythonJar = Get-ChildItem -LiteralPath (Join-Path $gradleCache 'caches/modules-2/files-2.1/com.chaquo.python.runtime/chaquopy_java/17.0.0') -Recurse -Filter 'chaquopy_java-17.0.0.jar' | Select-Object -First 1
if (-not $pythonJar) { throw 'The installed Chaquopy Java runtime is required for the compile check.' }
New-Item -ItemType Directory -Path (Join-Path $appCheck 'libs') -Force | Out-Null
Copy-Item -LiteralPath $pythonJar.FullName -Destination (Join-Path $appCheck 'libs/chaquopy_java-17.0.0.jar')
@'
plugins { id("com.android.library") }
android {
    namespace = "com.xinyu.xinyu_flutter"
    compileSdk = 36
    defaultConfig { minSdk = 24 }
    compileOptions { sourceCompatibility = JavaVersion.VERSION_17; targetCompatibility = JavaVersion.VERSION_17 }
}
dependencies {
    implementation(project(":phone_bridge"))
    implementation("io.flutter:flutter_embedding_debug:1.0.0-ENGINE_HASH")
    implementation(files("libs/chaquopy_java-17.0.0.jar"))
}
'@.Replace('ENGINE_HASH', $engine) | Set-Content (Join-Path $appCheck 'build.gradle.kts') -Encoding utf8
@'
pluginManagement { repositories { google(); mavenCentral(); gradlePluginPortal() } }
dependencyResolutionManagement { repositories { google(); mavenCentral(); maven("https://storage.googleapis.com/download.flutter.io"); maven("https://chaquo.com/maven") } }
plugins {
    id("com.android.library") version "9.1.0" apply false
    id("org.jetbrains.kotlin.android") version "2.4.0" apply false
}
rootProject.name = "XinYuFloatingChatChecks"
include(":droid_mcp", ":phone_bridge", ":app_check")
'@ | Set-Content (Join-Path $stage 'settings.gradle.kts') -Encoding utf8
('sdk.dir=' + $AndroidSdk.Replace('\','/')) | Set-Content (Join-Path $stage 'local.properties') -Encoding utf8
@'
org.gradle.jvmargs=-Xmx1536m -Dfile.encoding=UTF-8
android.useAndroidX=true
'@ | Set-Content (Join-Path $stage 'gradle.properties') -Encoding utf8
$env:JAVA_HOME = $JavaDirectory
# Robolectric resolves Android framework jars independently of Gradle. Keep any
# newly required SDKs beside this check output, never in the system-drive cache.
$roboCache = Join-Path ([IO.Path]::GetFullPath($Output)) '../robolectric-cache'
New-Item -ItemType Directory -Path $roboCache -Force | Out-Null
$oldAndroidCache = Join-Path $env:USERPROFILE '.m2/repository/org/robolectric/android-all-instrumented'
if (Test-Path -LiteralPath $oldAndroidCache) {
    & robocopy $oldAndroidCache (Join-Path $roboCache 'org/robolectric/android-all-instrumented') /E /NFL /NDL /NJH /NJS /NP /R:1 /W:1
    if ($LASTEXITCODE -ge 8) { throw 'Robolectric cache staging failed.' }
}
@'
allprojects {
    tasks.withType<org.gradle.api.tasks.testing.Test>().configureEach {
        systemProperty("maven.repo.local", "ROBO_CACHE")
        systemProperty("robolectric.dependency.repo.url", "https://repo.maven.apache.org/maven2")
        systemProperty("xinyu.visual.output", "VISUAL_OUTPUT")
    }
}
'@.Replace('ROBO_CACHE', $roboCache.Replace('\','/')).Replace('VISUAL_OUTPUT', ([IO.Path]::GetFullPath($Output)).Replace('\','/')) | Set-Content (Join-Path $stage 'test-cache.init.gradle.kts') -Encoding utf8
Push-Location $stage
try {
    & ./gradlew.bat :phone_bridge:testDebugUnitTest :app_check:compileDebugKotlin --offline --no-daemon --console=plain --init-script test-cache.init.gradle.kts *> (Join-Path $Output $LogName)
    $checkExit = $LASTEXITCODE
} finally { Pop-Location }
Get-Content (Join-Path $Output $LogName) -Tail 35
exit $checkExit
