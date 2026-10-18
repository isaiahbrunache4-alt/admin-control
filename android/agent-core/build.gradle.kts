import org.jetbrains.kotlin.gradle.dsl.JvmTarget

// Everything an Android Agent decides, with no Android in it, so it runs and is tested
// on any JVM: verifying bundles, schedules, matching and the Agent protocol.
plugins {
    id("org.jetbrains.kotlin.jvm")
}

java {
    sourceCompatibility = JavaVersion.VERSION_17
    targetCompatibility = JavaVersion.VERSION_17
}

kotlin {
    compilerOptions { jvmTarget.set(JvmTarget.JVM_17) }
}

dependencies {
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.10.0")
    implementation("org.bouncycastle:bcprov-jdk18on:1.83")   // Ed25519 on every Android version

    testImplementation(kotlin("test"))
}

tasks.test {
    useJUnitPlatform()
    // Shared with Core: testdata/fortress_vectors.json (docs/agent_protocol.md).
    systemProperty("fortress.vectors", rootProject.file("../testdata/fortress_vectors.json").absolutePath)
    // Live test against a running Core, when these are set (see LiveCoreTest).
    listOf("FORTRESS_AGENT_URL", "FORTRESS_ENROL_CODE", "FORTRESS_DEVICE_ID").forEach { name ->
        System.getenv(name)?.let { environment(name, it) }
    }
    testLogging { events("failed"); exceptionFormat = org.gradle.api.tasks.testing.logging.TestExceptionFormat.FULL }
}
