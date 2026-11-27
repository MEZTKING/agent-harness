---
name: Godot 4 scenes
when: Making scenes and scripts for a Godot 4 game.
tags: [gdscript, game-logic, kind:godot-game]
---
- One scene per thing (player, enemy, level, menu), each with its own script; build bigger scenes by instancing smaller ones.
- Scripts start with `extends <NodeType>`; use typed GDScript (`var speed: float = 200.0`, `func hit(amount: int) -> void:`).
- Physics movement goes in `_physics_process(delta)`; a `CharacterBody2D` sets `velocity` then calls `move_and_slide()`.
- Read input through actions named in the Input Map (`Input.get_axis("move_left", "move_right")`), not raw keys.
- Talk upwards with signals (`signal died`, `died.emit()`), downwards by calling child nodes; avoid long `get_node("../../..")` paths. `@onready var sprite := $Sprite2D` for children.
- `@export` the numbers a designer may tune.
- Groups (`add_to_group("enemies")`) find many nodes of one kind.
- Scene files (`.tscn`) are text: keep edits small and keep their `uid`s and resource ids as they are.
- A game that should be checked headless must start without a window-only node failing; run it with `godot --headless` to see errors.
