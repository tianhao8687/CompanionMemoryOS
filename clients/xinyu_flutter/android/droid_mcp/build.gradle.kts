plugins {
    id("com.android.library")
}

android {
    namespace = "com.xinyu.droid_mcp"
    compileSdk = 36
    // Preserve installation on older devices. PhoneBridge gates all SDK entry
    // points at API 28, matching upstream's supported Android version.
    defaultConfig { minSdk = 24 }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.17.0")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.11.0")
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.11.0")
}
