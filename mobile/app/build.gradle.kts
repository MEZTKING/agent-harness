import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
    id("org.jetbrains.kotlin.plugin.serialization")
}

// Version from the desktop app's pyproject.toml, so the phone and the PC release together.
val appVersion: String = Regex("""^version\s*=\s*"([^"]+)"""", RegexOption.MULTILINE)
    .find(rootProject.file("../pyproject.toml").readText())!!.groupValues[1]
val parts = appVersion.split(".").map { it.toIntOrNull() ?: 0 }
val code = parts.getOrElse(0) { 0 } * 10000 + parts.getOrElse(1) { 0 } * 100 + parts.getOrElse(2) { 0 }

// Release signing: from CI secrets (ROUNDTABLE_KEYSTORE_*) or a local mobile/signing folder that is
// never committed. Without either, release builds use the debug key (fine for trying it out, but a
// later properly signed build can't update it in place).
val signingProps = Properties().apply {
    val f = rootProject.file("signing/signing.properties")
    if (f.exists()) f.inputStream().use { load(it) }
}

android {
    namespace = "com.meztking.roundtable"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.meztking.roundtable"
        minSdk = 26
        targetSdk = 35
        versionCode = code
        versionName = appVersion
    }

    signingConfigs {
        create("release") {
            val envStore = System.getenv("ROUNDTABLE_KEYSTORE_FILE")
            storeFile = if (!envStore.isNullOrBlank()) file(envStore) else rootProject.file("signing/roundtable.jks")
            storePassword = System.getenv("ROUNDTABLE_KEYSTORE_PASSWORD") ?: signingProps.getProperty("storePassword")
            keyAlias = System.getenv("ROUNDTABLE_KEY_ALIAS") ?: signingProps.getProperty("keyAlias")
            keyPassword = System.getenv("ROUNDTABLE_KEY_PASSWORD") ?: signingProps.getProperty("keyPassword")
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
            val release = signingConfigs.getByName("release")
            signingConfig = if (release.storeFile?.exists() == true && release.storePassword != null) release
            else signingConfigs.getByName("debug")
        }
        debug {
            applicationIdSuffix = ".debug"
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
        freeCompilerArgs += listOf(
            "-opt-in=androidx.compose.material3.ExperimentalMaterial3Api",
            "-opt-in=androidx.compose.foundation.layout.ExperimentalLayoutApi",
        )
    }
    buildFeatures { compose = true; buildConfig = true }
    packaging { resources { excludes += "/META-INF/{AL2.0,LGPL2.1}" } }
    testOptions {
        unitTests {
            isIncludeAndroidResources = true
            // Screenshots of the main screens (Robolectric, no emulator): ./gradlew testDebugUnitTest -Pscreenshots
            // writes PNGs to app/build/screenshots. Without -Pscreenshots the screenshot tests only check that the screens draw.
            all {
                it.systemProperty("roborazzi.test.record", if (project.hasProperty("screenshots")) "true" else "false")
                it.systemProperty("screenshots.dir", layout.buildDirectory.dir("screenshots").get().asFile.absolutePath)
                // where Robolectric downloads Android itself from (-ProbolectricRepo=<maven mirror> when Maven Central is busy)
                project.findProperty("robolectricRepo")?.let { url -> it.systemProperty("robolectric.dependency.repo.url", url.toString()) }
            }
        }
    }
}

dependencies {
    val composeBom = platform("androidx.compose:compose-bom:2024.12.01")
    implementation(composeBom)
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.material:material-icons-extended")
    implementation("androidx.activity:activity-compose:1.9.3")
    implementation("androidx.core:core-ktx:1.15.0")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.8.7")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.8.7")
    implementation("androidx.navigation:navigation-compose:2.8.5")
    implementation("androidx.work:work-runtime-ktx:2.10.0")
    implementation("androidx.security:security-crypto:1.1.0-alpha06")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.7.3")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.9.0")
    implementation("com.journeyapps:zxing-android-embedded:4.3.0")
    debugImplementation("androidx.compose.ui:ui-tooling")
    debugImplementation("androidx.compose.ui:ui-test-manifest")

    testImplementation("junit:junit:4.13.2")
    testImplementation("com.squareup.okhttp3:mockwebserver:4.12.0")
    testImplementation("org.jetbrains.kotlinx:kotlinx-coroutines-test:1.9.0")
    testImplementation("org.robolectric:robolectric:4.14.1")
    testImplementation("io.github.takahirom.roborazzi:roborazzi:1.36.0")
    testImplementation("io.github.takahirom.roborazzi:roborazzi-compose:1.36.0")
    testImplementation("androidx.compose.ui:ui-test-junit4")
}
