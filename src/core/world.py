from __future__ import annotations

from typing import TYPE_CHECKING, Iterable

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
        for entity in sorted(self._entities, key=lambda item: item.layer):
            if entity.alive:
                entity.draw(screen, self, app, camera)

    def entities_with_group(self, group: str) -> Iterable[Entity]:
        return (
            entity
            for entity in self._entities
            if entity.alive and entity.collision_group == group
        )

    def first_with_group(self, group: str) -> Entity | None:
        return next(iter(self.entities_with_group(group)), None)
