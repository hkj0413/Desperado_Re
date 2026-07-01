from __future__ import annotations

from typing import TYPE_CHECKING, Iterable

import pygame

from src.core.camera import Camera, WorldBounds
from src.core.collision import CollisionSystem

if TYPE_CHECKING:
    import pygame

    from src.app import GameApp
    from src.gameplay.entities.base import Entity


class World:
    """Owns runtime world entities, bounds, and collision checks.

    The World contains only world-space data. Camera movement does not change
    any entity coordinates or collision results; it is used only in draw().
    """

    def __init__(self, bounds: WorldBounds) -> None:
        self.bounds = bounds
        self._entities: list[Entity] = []
        self._pending_add: list[Entity] = []
        self._pending_remove: set[Entity] = set()
        self.collisions = CollisionSystem()

    def add(self, entity: Entity) -> None:
        self._pending_add.append(entity)

    def remove(self, entity: Entity) -> None:
        entity.alive = False
        self._pending_remove.add(entity)

    def commit(self) -> None:
        if self._pending_remove:
            self._entities = [
                entity
                for entity in self._entities
                if entity not in self._pending_remove
            ]
            self._pending_remove.clear()

        if self._pending_add:
            self._entities.extend(self._pending_add)
            self._pending_add.clear()

    def update(self, delta_seconds: float, app: GameApp) -> None:
        self.commit()

        # A tuple snapshot makes update-safe removal possible. Entity updates
        # may request removal without skipping the next entity.
        for entity in tuple(self._entities):
            if entity.alive:
                entity.update(delta_seconds, self, app)

        self.commit()
        self.collisions.check(self, app)
        self.commit()

    def draw(self, screen: pygame.Surface, app: GameApp, camera: Camera) -> None:
        # First render every world actor in its normal layer order.
        visible_entities: list[Entity] = []

        for entity in sorted(self._entities, key=lambda item: item.layer):
            if not entity.alive:
                continue

            entity.draw(screen, self, app, camera)
            visible_entities.append(entity)

        # The debug rectangles are deliberately drawn after *all* world actors,
        # so the red borders sit on top of players, terrain, enemies, items,
        # portals, and projectiles. Hud is not part of World.draw().
        if app.debug_draw_actor_bounds:
            for entity in visible_entities:
                self._draw_debug_actor_bounds(screen, entity, camera)

    @staticmethod
    def _draw_debug_actor_bounds(
        screen: pygame.Surface,
        entity: Entity,
        camera: Camera,
    ) -> None:
        """Draw an actor's real world-space width/height box in red."""

        if not camera.is_world_rect_visible(
            entity.x,
            entity.y,
            entity.width,
            entity.height,
        ):
            return

        rect = camera.rect_from_world_center(
            entity.x,
            entity.y,
            entity.width,
            entity.height,
        )
        pygame.draw.rect(screen, (255, 0, 0), rect, width=2)

    def entities_with_group(self, group: str) -> Iterable[Entity]:
        return (
            entity
            for entity in self._entities
            if entity.alive and entity.collision_group == group
        )

    def first_with_group(self, group: str) -> Entity | None:
        return next(iter(self.entities_with_group(group)), None)
