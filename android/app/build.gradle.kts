plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
}

android {
    namespace = "uk.osianj.companion"
    compileSdk = 35

    defaultConfig {
        applicationId = "uk.osianj.companion"
        minSdk = 26
        targetSdk = 35
        versionCode = 22
        versionName = "1.1.0"
    }

    // If app/debug.keystore exists, every build is signed with that same key, so a new APK installs over the
    // previous one and keeps the app's saved pairing. The file is NOT in git (see .gitignore): copy it in from
    // your own backup. Without it Android Gradle Plugin falls back to its per-machine debug key, and the first
    // install onto a phone that has a differently-signed copy needs an uninstall first (which wipes the pairing).
    val bundledKey = file("debug.keystore")
    if (bundledKey.exists()) {
        signingConfigs {
            getByName("debug") {
                storeFile = bundledKey
                storePassword = "android"
                keyAlias = "androiddebugkey"
                keyPassword = "android"
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            signingConfig = signingConfigs.getByName("debug")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
    buildFeatures { compose = true }
}

dependencies {
    implementation("androidx.core:core-ktx:1.15.0")
    implementation("androidx.activity:activity-compose:1.9.3")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.8.7")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.8.7")

    implementation(platform("androidx.compose:compose-bom:2024.12.01"))
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.foundation:foundation")
    implementation("androidx.compose.material3:material3")

    implementation("com.squareup.okhttp3:okhttp:4.12.0")

    // JVM unit tests (the chat state reducer is plain Kotlin + org.json)
    testImplementation("junit:junit:4.13.2")
    testImplementation("org.json:json:20240303")
}
