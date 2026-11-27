---
name: Android apps with Compose
when: Writing screens and logic for an Android app in Kotlin with Jetpack Compose.
tags: [kotlin, layout, kind:android-app]
---
- A screen is a `@Composable` function that takes its state and callbacks as parameters; keep the state in a `ViewModel` and expose it as a `StateFlow`, collected with `collectAsState()`.
- `remember { mutableStateOf(...) }` only for state that belongs to the screen itself (a text field being typed).
- Long work runs in `viewModelScope.launch` on `Dispatchers.IO`; never block the main thread with network or disk.
- Use Material 3 components and the theme's colours and typography, not hard-coded colours.
- Every image and icon button has a `contentDescription` (or `null` when it is decoration); touch targets at least 48 dp.
- Strings the user reads go in `res/values/strings.xml`.
- Lists use `LazyColumn` with stable `key`s.
- Keep logic in plain Kotlin classes with no Android imports, so it can be unit-tested with JUnit on the computer.
- Build with `./gradlew assembleDebug` and run `./gradlew testDebugUnitTest` before finishing.
