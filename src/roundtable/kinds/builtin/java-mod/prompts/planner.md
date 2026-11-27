This project is a mod for a Java game, built with Gradle. Plan it so it builds with one command,
`./gradlew build`, and the mod file lands in `build/libs/`. The first task sets up the Gradle project
with the wrapper (`gradlew`, `gradlew.bat`, `gradle/wrapper/`), the mod's id, its package and the mod
file the loader reads (`fabric.mod.json` for Fabric, `META-INF/neoforge.mods.toml` or `mods.toml` for
the others). Name the game version and loader version in the spec; when unsure, say so rather than guess.
