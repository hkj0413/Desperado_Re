from __future__ import annotations

from math import dist
from typing import TYPE_CHECKING, Any

import pygame

from src.gameplay.entities.base import Entity

if TYPE_CHECKING:
    from src.app import GameApp
    from src.core.camera import Camera
    from src.core.world import World
    from src.gameplay.entities.player import Player


class Enemy(Entity):
    """Data-driven shared enemy shell.

    Distance to the player and HP visibility are calculated in WORLD space.
    Camera conversion happens only while rendering the sprite / HP bar.
    """

    def __init__(self, enemy_id: str, definition: dict[str, Any], x: float, y: float) -> None:
        visual = definition['visual']
        super().__init__(
            x=x,
            y=y,
            width=float(visual['width']),
            height=float(visual['height']),
            layer=20,
            collision_group='enemy',
        )
        self.enemy_id = enemy_id
        self.display_name = definition['display_name']
        self.definition = definition
        self.color = tuple(visual['placeholder_color'])

        self.max_hp = int(definition['stats']['max_hp'])
        self.hp = self.max_hp
        self.hp_show_distance = float(definition['ui']['hp_show_distance'])
        self.hp_bar_offset_y = int(definition['ui'].get('hp_bar_offset_y', 12))
        self.hit_invulnerability_seconds = float(
            definition['stats'].get('hit_invulnerability_seconds', 0.0)
        )
        self._can_be_hit_at = 0.0

    def take_damage(self, damage: int, app: GameApp) -> bool:
        if app.timer.game_time < self._can_be_hit_at:
            return False

        self._can_be_hit_at = app.timer.game_time + self.hit_invulnerability_seconds
        self.hp = max(0, self.hp - damage)
        return True

    def is_near_player(self, player: Player | None) -> bool:
        if player is None:
            return False
        return dist((self.x, self.y), (player.x, player.y)) <= self.hp_show_distance

    def update(self, delta_seconds: float, world: World, app: GameApp) -> None:
        if self.hp <= 0:
            world.remove(self)

    def draw(
        self,
        screen: pygame.Surface,
        world: World,
        app: GameApp,
        camera: Camera,
    ) -> None:
        if not camera.is_world_rect_visible(self.x, self.y, self.width, self.height):
            return

        rect = camera.rect_from_world_center(self.x, self.y, self.width, self.height)
        pygame.draw.rect(screen, self.color, rect, border_radius=5)
        pygame.draw.rect(screen, (55, 30, 30), rect, width=2, border_radius=5)

        player = world.first_with_group('player')
        if self.is_near_player(player):
            self._draw_hp_bar(screen, camera)

    def _draw_hp_bar(self, screen: pygame.Surface, camera: Camera) -> None:
        bar_width = max(56, int(self.width))
        bar_height = 8
        screen_x, screen_y = camera.world_to_screen(self.x, self.y)
        x = int(screen_x - bar_width * 0.5)
        y = int(screen_y - self.height * 0.5 - self.hp_bar_offset_y)
        ratio = self.hp / self.max_hp

        pygame.draw.rect(screen, (42, 42, 48), (x, y, bar_width, bar_height), border_radius=3)
        pygame.draw.rect(screen, (214, 72, 72), (x, y, int(bar_width * ratio), bar_height), border_radius=3)
        pygame.draw.rect(screen, (230, 230, 230), (x, y, bar_width, bar_height), width=1, border_radius=3)
