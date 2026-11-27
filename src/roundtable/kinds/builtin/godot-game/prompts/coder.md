This project is a Godot 4 game. Write scenes (.tscn) and GDScript (.gd) as text, using Godot 4 names
(CharacterBody2D, move_and_slide() without arguments, @export, signal.connect()). Read the controls
through the input actions in project.godot (Input.is_action_pressed("jump")), never through raw keys,
so the harness can play it. Use the run_game tool after each change and fix every error it reports.
