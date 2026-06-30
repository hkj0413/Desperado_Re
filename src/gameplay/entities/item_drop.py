from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pygame

from src.gameplay.entities.base import Entity

if TYPE_CHECKING:
    from src.app import GameApp
    from src.core.camera import Camera
    from src.core.world import World


class ItemDrop(Entity):
    """An item pickup located in WORLD space."""

    def __init__(self, item_id: str, definition: dict[str, Any], x: float, y: float) -> None:
        super().__init__(x, y, 26, 26, layer=15, collision_group='item')
        self.item_id = item_id
        self.definition = definition
        self.color = tuple(definition['visual']['placeholder_color'])

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
        pygame.draw.rect(screen, self.color, rect, border_radius=4)
        pygame.draw.rect(screen, (230, 245, 235), rect, width=2, border_radius=4)
