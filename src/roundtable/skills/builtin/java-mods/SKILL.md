---
name: Java game mods
when: Writing a Java mod for a game (for example a Minecraft mod with Fabric or similar).
tags: [java, game-logic, kind:java-mod]
---
- Follow the mod loader's own template project: its build file, its metadata file (mod id, version, entry points) and its folder layout. Don't invent your own.
- Keep the mod id lower-case and the same everywhere (metadata, assets folder, registry names).
- Register blocks, items and the like once, in the loader's initialiser, using the game's registries; never at random times later.
- Assets and data (models, textures, language files, recipes) go under `assets/<modid>/` and `data/<modid>/` as the game expects; JSON must be valid.
- Code that only runs on the player's computer (rendering, key bindings, screens) goes in the client entry point, so a server never loads it.
- Check the exact game and loader versions in the build file before using an API; names change between versions. If unsure, say so rather than guess.
- Build with the project's Gradle wrapper (`./gradlew build`); the mod is the jar in `build/libs/`.
