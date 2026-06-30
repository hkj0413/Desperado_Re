from __future__ import annotations

from typing import TYPE_CHECKING

import pygame

from src.gameplay.entities.base import Entity

if TYPE_CHECKING:
    from src.app import GameApp
    from src.core.camera import Camera
    from src.core.world import World


class TerrainBlock(Entity):
    """Static world terrain placeholder.

    Terrain stores world-space rectangles. A future movement resolver can use
    its existing AABB without knowing anything about camera scrolling.
    """

    def __init__(self, x: float, y: float, width: float, height: float, kind: str = 'floor') -> None:
        super().__init__(x, y, width, height, layer=10, collision_group='terrain')
        self.kind = kind

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
        pygame.draw.rect(screen, (62, 68, 78), rect)
        pygame.draw.rect(screen, (105, 115, 128), rect, width=2)
