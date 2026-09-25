plugins {
    id("com.android.application")
    // The Flutter Gradle Plugin must be applied after the Android and Kotlin Gradle plugins.
    id("dev.flutter.flutter-gradle-plugin")
    id("com.chaquo.python")
}

android {
    namespace = "com.xinyu.xinyu_flutter"
    compileSdk = 36
    ndkVersion = flutter.ndkVersion

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    defaultConfig {
        // TODO: Specify your own unique Application ID (https://developer.android.com/studio/build/application-id.html).
        applicationId = "com.xinyu.xinyu_flutter"
        // You can update the following values to match your application needs.
        // For more information, see: https://flutter.dev/to/review-gradle-config.
        minSdk = 24
        ndk {
            // Flutter adds default ABIs before this block; Python 3.13 is 64-bit only.
            abiFilters.clear()
            abiFilters += listOf("arm64-v8a")
        }
        targetSdk = 36
        externalNativeBuild {
            cmake {
                arguments += "-DXINYU_SQLITE_SOURCE=" + (System.getenv("XINYU_SQLITE_SOURCE")
                    ?: "${project.projectDir}/../../engine/sqlite/sqlite3.c").replace('\\', '/')
            }
        }
        // Uses the version code from pubspec.yaml. When using split APKs, 1000 * ABI_VERSION
        // is added automatically by Flutter. (https://developer.android.com/studio/build/configure-apk-splits#configure-APK-versions)
        // You can force using the value of versionCode by specifying the `-P force-version-code-ignoring-abi=true`
        // flag during build.
        versionCode = flutter.versionCode
        versionName = flutter.versionName
    }

    buildTypes {
        release {
            proguardFiles("proguard-rules.pro")
            // TODO: Add your own signing config for the release build.
            // Signing with the debug keys for now, so `flutter run --release` works.
            signingConfig = signingConfigs.getByName("debug")
        }
    }
    externalNativeBuild {
        cmake {
            path = file("src/main/cpp/CMakeLists.txt")
            version = "3.22.1"
        }
    }
    packaging {
        jniLibs {
            // Prefer the app's FTS5-enabled SQLite to the dependency's minimal copy.
            // The final APK check rejects a copy without FTS5.
            pickFirsts += "**/libsqlite3_python.so"
            keepDebugSymbols += "**/libsqlite3_python.so"
        }
    }
}

chaquopy {
    defaultConfig {
        version = "3.13"
        System.getenv("XINYU_BUILD_PYTHON")?.let { buildPython(it) }
        pip {
            // Prepared wheels must be actual Android binaries, never desktop wheels.
            options("--find-links", System.getenv("XINYU_ANDROID_WHEELS")
                ?: "${project.projectDir}/../../engine/wheels")
            install("-r", "${project.projectDir}/../../engine/requirements-android.txt")
        }
        extractPackages("companion_agent", "companion_memoryos")
    }
    sourceSets {
        getByName("main") { srcDir(System.getenv("XINYU_ENGINE_SOURCES") ?: "../../engine/python") }
    }
}

kotlin {
    compilerOptions {
        jvmTarget = org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17
    }
}

flutter {
    source = "../.."
}
