import java.util.Properties

plugins {
    id("com.android.application")
}

// Release signing (Spec 01 §7.1, Phase 5). A device-owner app can only be updated by an
// APK signed with the same key, so the key is made once, kept with the Fortress password,
// and never committed. android/keystore.properties holds:
//   storeFile=fortress-release.jks
//   storePassword=…
//   keyAlias=fortress
//   keyPassword=…
val keystoreFile = rootProject.file("keystore.properties")
val keystore = Properties().apply { if (keystoreFile.exists()) keystoreFile.inputStream().use(::load) }

android {
    namespace = "com.fortress.agent"
    compileSdk = 36

    defaultConfig {
        applicationId = "com.fortress.agent"
        minSdk = 33            // Android 13+; the Pixel 8a and the Idea Tab run Android 16
        targetSdk = 36
        versionCode = 5
        versionName = "0.5.0"
    }

    signingConfigs {
        if (keystoreFile.exists()) {
            create("release") {
                storeFile = rootProject.file(keystore.getProperty("storeFile"))
                storePassword = keystore.getProperty("storePassword")
                keyAlias = keystore.getProperty("keyAlias")
                keyPassword = keystore.getProperty("keyPassword")
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            signingConfig = signingConfigs.findByName("release") // unsigned without keystore.properties
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    buildFeatures {
        buildConfig = true
    }
}

dependencies {
    implementation(project(":agent-core"))
}
