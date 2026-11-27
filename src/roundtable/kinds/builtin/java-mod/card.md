A mod for a Java game such as Minecraft, built with Gradle into a .jar file.

At the end the harness builds it with `./gradlew build`, checks the .jar is a real one and holds its mod
file (fabric.mod.json or mods.toml), and marks it done only then. It needs Java on this computer. Starting
the game with the mod is still checked by hand on the owner's PC.
