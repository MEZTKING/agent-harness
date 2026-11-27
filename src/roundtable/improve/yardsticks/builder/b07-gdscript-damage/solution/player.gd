extends CharacterBody2D

signal died

var health: int = 100


func _ready() -> void:
	pass


func take_damage(amount: int) -> void:
	health = max(health - amount, 0)
	if health == 0:
		died.emit()
