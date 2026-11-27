A native Android app in Kotlin (Jetpack Compose), built with the Gradle wrapper as a debug APK.

At the end the harness builds it with `./gradlew assembleDebug`, checks the APK is a real one with the
SDK's own tools when they are here, and installs it only on an emulator that is already running – never
on a plugged-in phone, and never signed with a real key. It needs Java and the Android SDK.
