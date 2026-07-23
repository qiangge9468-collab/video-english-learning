plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

val enableWhisperNative = providers.gradleProperty("enableWhisperNative")
    .map { it.equals("true", ignoreCase = true) }
    .orElse(false)
    .get()

providers.gradleProperty("codexTempBuildDir").orNull?.let { tempBuildDir ->
    layout.buildDirectory.set(file(tempBuildDir))
}

android {
    namespace = "com.codex.videolearnenglish"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.codex.videolearnenglish.remote"
        minSdk = 26
        targetSdk = 35
        versionCode = 24
        versionName = "2.0.4"

        if (enableWhisperNative) {
            ndk {
                abiFilters += listOf("arm64-v8a")
            }
            externalNativeBuild {
                cmake {
                    cppFlags += listOf("-std=c++17")
                }
            }
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }

    if (enableWhisperNative) {
        ndkVersion = "30.0.14904198"
        externalNativeBuild {
            cmake {
                path = file("src/main/cpp/CMakeLists.txt")
                version = "4.1.2"
            }
        }
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("com.google.android.material:material:1.12.0")
    implementation("com.google.mlkit:translate:17.0.3")
}
