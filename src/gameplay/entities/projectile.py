from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pygame

from src.gameplay.entities.base import Entity
from src.gameplay.projectile_assets import ProjectileSpriteCache

if TYPE_CHECKING:
    from src.app import GameApp
    from src.core.camera import Camera
    from src.core.world import World


class Projectile(Entity):
    updates_each_frame = True
    """A world-space projectile for either player or enemy skills.

    ``collision_group`` determines which collision rule receives it:
    - player_projectile -> enemy
    - enemy_projectile  -> player
    """

    def __init__(
        self,
        skill_id: str,
        skill_definition: dict[str, Any],
        x: float,
        y: float,
        direction: int,
        *,
        collision_group: str = 'player_projectile',
    ) -> None:
        projectile = skill_definition['projectile']
        super().__init__(
            x=x,
            y=y,
            width=float(projectile.get('width', 12)),
            height=float(projectile.get('height', 8)),
            layer=18,
            collision_group=collision_group,
        )
        self.skill_id = skill_id
        self.skill_definition = skill_definition
        self.projectile_definition = projectile
        self.damage = int(projectile['damage'])
        self.speed = float(projectile['speed'])
        self.remaining_lifetime = float(projectile['lifetime_seconds'])
        self.remaining_hits = int(projectile.get('pierce_count', 0)) + 1
        self.direction = 1 if direction >= 0 else -1
        self.color = tuple(projectile.get('placeholder_color', [255, 255, 255]))
        self.stun_seconds = max(
            0.0,
            float(projectile.get('stun_seconds', 0.0)),
        )
        self._hit_target_ids: set[int] = set()

    def update(
        self,
        delta_seconds: float,
        world: World,
        app: GameApp,
    ) -> None:
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

    def register_target_hit(
        self,
        target: object,
        world: World,
    ) -> bool:
        target_key = id(target)
        if target_key in self._hit_target_ids:
            return False

        self._hit_target_ids.add(target_key)
        self.remaining_hits -= 1
        if self.remaining_hits <= 0:
            world.remove(self)
        return True

    def register_enemy_hit(self, enemy: object, world: World) -> bool:
        """Compatibility name for player-projectile enemy hit handling."""

        return self.register_target_hit(enemy, world)

    def draw(
        self,
        screen: pygame.Surface,
        world: World,
        app: GameApp,
        camera: Camera,
    ) -> None:
        draw_width = float(
            self.projectile_definition.get('draw_width', self.width)
        )
        draw_height = float(
            self.projectile_definition.get('draw_height', self.height)
        )

        if not camera.is_world_rect_visible(
            self.x,
            self.y,
            draw_width,
            draw_height,
            padding=8.0,
        ):
            return

        rect = camera.rect_from_world_center(
            self.x,
            self.y,
            draw_width,
            draw_height,
        )
        image = ProjectileSpriteCache.get_surface(
            app,
            self.projectile_definition,
            self.direction,
        )

        if image is not None:
            screen.blit(image, rect.topleft)
        else:
            pygame.draw.rect(screen, self.color, rect, border_radius=3)
