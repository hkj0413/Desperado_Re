from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pygame

from src.gameplay.entities.base import Entity

if TYPE_CHECKING:
    from src.app import GameApp
    from src.core.camera import Camera
    from src.core.world import World


class Projectile(Entity):
    """A skill projectile that moves and collides entirely in WORLD space."""

    def __init__(
        self,
        skill_id: str,
        skill_definition: dict[str, Any],
        x: float,
        y: float,
        direction: int,
    ) -> None:
        projectile = skill_definition['projectile']
        super().__init__(
            x=x,
            y=y,
            width=float(projectile.get('width', 12)),
            height=float(projectile.get('height', 8)),
            layer=18,
            collision_group='player_projectile',
        )
        self.skill_id = skill_id
        self.damage = int(projectile['damage'])
        self.speed = float(projectile['speed'])
        self.remaining_lifetime = float(projectile['lifetime_seconds'])
        self.remaining_hits = int(projectile.get('pierce_count', 0)) + 1
        self.direction = 1 if direction >= 0 else -1
        self.color = tuple(projectile.get('placeholder_color', [255, 255, 255]))
        self._hit_enemy_ids: set[int] = set()

    def update(self, delta_seconds: float, world: World, app: GameApp) -> None:
        self.x += self.direction * self.speed * delta_seconds
        self.remaining_lifetime -= delta_seconds

        margin = 100.0
        bounds = world.bounds
        outside_world = (
                self.x < bounds.left - margin
                or self.x > bounds.right + margin
                or self.y < bounds.bottom - margin
                or self.y > bounds.top + margin
        )

        if self.remaining_lifetime <= 0.0 or outside_world:
            world.remove(self)

    def register_enemy_hit(self, enemy: object, world: World) -> bool:
        enemy_key = id(enemy)
        if enemy_key in self._hit_enemy_ids:
            return False

        self._hit_enemy_ids.add(enemy_key)
        self.remaining_hits -= 1
        if self.remaining_hits <= 0:
            world.remove(self)
        return True

    def draw(
        self,
        screen: pygame.Surface,
        world: World,
        app: GameApp,
        camera: Camera,
    ) -> None:
        if not camera.is_world_rect_visible(self.x, self.y, self.width, self.height, padding=8.0):
            return

        rect = camera.rect_from_world_center(self.x, self.y, self.width, self.height)
        pygame.draw.rect(screen, self.color, rect, border_radius=3)
