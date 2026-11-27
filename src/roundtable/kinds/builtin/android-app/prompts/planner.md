This project is a native Android app in Kotlin with Jetpack Compose, built with Gradle. Plan it so
`./gradlew assembleDebug` builds it and the APK lands in `app/build/outputs/apk/debug/`. The first task
sets up the project with the Gradle wrapper (`gradlew`, `gradlew.bat`, `gradle/wrapper/`), `settings.gradle.kts`,
the `app` module, its package name and the manifest. Use only the debug build: no release signing.
