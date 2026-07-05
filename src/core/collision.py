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
    """Checks explicitly registered category pairs through a spatial hash."""

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
        if not self._rules:
            return

        # Entity positions are final for this frame at this point. Rebuilding
        # a tiny grid is far cheaper than testing every projectile against every
        # enemy as projectile and enemy counts rise.
        groups = {
            group
            for rule in self._rules
            for group in (rule.group_a, rule.group_b)
        }
        world.rebuild_collision_index(groups)

        for rule in self._rules:
            group_a = world.entities_with_group(rule.group_a)

            for entity_a in group_a:
                if (
                    not entity_a.alive
                    or not world.is_collision_active(entity_a)
                ):
                    continue

                collider_a = world.collision_aabb(entity_a)
                if collider_a is None:
                    continue

                for entity_b in world.collision_candidates(
                    rule.group_b,
                    collider_a,
                ):
                    if entity_a is entity_b or not entity_b.alive:
                        continue

                    collider_b = world.collision_aabb(entity_b)
                    if collider_b is None:
                        continue

                    if collider_a.intersects(collider_b):
                        rule.handler(
                            entity_a,
                            entity_b,
                            world,
                            app,
                        )
