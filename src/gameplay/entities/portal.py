from __future__ import annotations

from typing import TYPE_CHECKING

import pygame

from src.gameplay.entities.base import Entity

if TYPE_CHECKING:
    from src.app import GameApp
    from src.core.camera import Camera
    from src.core.world import World


class Portal(Entity):
    """Stage portal stored and collided in WORLD space."""

    def __init__(self, x: float, y: float, width: float, height: float, target_stage_id: str) -> None:
        super().__init__(x, y, width, height, layer=12, collision_group='portal')
        self.target_stage_id = target_stage_id

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
        pygame.draw.rect(screen, (121, 98, 212), rect, border_radius=20)
        pygame.draw.rect(screen, (220, 210, 255), rect, width=2, border_radius=20)
