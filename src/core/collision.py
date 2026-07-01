from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from src.core.world import World
    from src.gameplay.entities.base import Entity


@dataclass(frozen=True)
class AABB:
    """Axis-aligned world-space collision rectangle.

    World coordinate convention:
    - left < right
    - bottom < top
    """

    left: float
    bottom: float
    right: float
    top: float

    def intersects(self, other: AABB) -> bool:
        return not (
            self.right <= other.left
            or self.left >= other.right
            or self.top <= other.bottom
            or self.bottom >= other.top
        )


CollisionHandler = Callable[[Any, Any, Any, Any], None]


@dataclass(frozen=True)
class CollisionRule:
    group_a: str
    group_b: str
    handler: CollisionHandler


class CollisionSystem:
    """Checks only explicitly registered collision category pairs."""

    def __init__(self) -> None:
        self._rules: list[CollisionRule] = []

    def register(
        self,
        group_a: str,
        group_b: str,
        handler: CollisionHandler,
    ) -> None:
        self._rules.append(
            CollisionRule(
                group_a,
                group_b,
                handler,
            )
        )

    def check(self, world: World, app: Any) -> None:
        for rule in self._rules:
            group_a = tuple(world.entities_with_group(rule.group_a))
            group_b = tuple(world.entities_with_group(rule.group_b))

            for entity_a in group_a:
                collider_a = entity_a.get_aabb()

                if collider_a is None or not entity_a.alive:
                    continue

                for entity_b in group_b:
                    if entity_a is entity_b or not entity_b.alive:
                        continue

                    collider_b = entity_b.get_aabb()

                    if collider_b is None:
                        continue

                    if collider_a.intersects(collider_b):
                        rule.handler(
                            entity_a,
                            entity_b,
                            world,
                            app,
                        )