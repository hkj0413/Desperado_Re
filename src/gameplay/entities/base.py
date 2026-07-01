from __future__ import annotations

from typing import TYPE_CHECKING

from src.core.collision import AABB

if TYPE_CHECKING:
    import pygame

    from src.app import GameApp
    from src.core.camera import Camera
    from src.core.world import World


class Entity:
    """Base class for all world objects.

    World coordinate convention:
    - left-bottom is (0, 0)
    - +x goes right
    - +y goes up

    x and y are always world-space center coordinates.
    """

    def __init__(
        self,
        x: float,
        y: float,
        width: float,
        height: float,
        *,
        layer: int,
        collision_group: str | None,
    ) -> None:
        self.x = x
        self.y = y
        self.width = width
        self.height = height

        self.layer = layer
        self.collision_group = collision_group
        self.alive = True

    def get_aabb(self) -> AABB | None:
        if self.collision_group is None:
            return None

        return AABB(
            left=self.x - self.width * 0.5,
            bottom=self.y - self.height * 0.5,
            right=self.x + self.width * 0.5,
            top=self.y + self.height * 0.5,
        )

    def update(
        self,
        delta_seconds: float,
        world: World,
        app: GameApp,
    ) -> None:
        pass

    def draw(
        self,
        screen: pygame.Surface,
        world: World,
        app: GameApp,
        camera: Camera,
    ) -> None:
        pass