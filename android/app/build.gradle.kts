plugins {
    id("com.android.application")
}

android {
    namespace = "com.fortress.agent"
    compileSdk = 36

    defaultConfig {
        applicationId = "com.fortress.agent"
        minSdk = 33            // Android 13+; the Pixel 8a and the Idea Tab run Android 16
        targetSdk = 36
        versionCode = 1
        versionName = "0.1.0"
    }

    buildTypes {
        release {
            isMinifyEnabled = true
            isShrinkResources = true
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
