from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pygame


@dataclass(frozen=True)
class WorldBounds:
    """The playable rectangle in world coordinates.

    World coordinates are the only coordinates used for movement, collision,
    distance checks, spawn positions, and stage boundaries.
    """

    left: float
    top: float
    right: float
    bottom: float

    @classmethod
    def from_mapping(cls, mapping: dict[str, Any]) -> WorldBounds:
        bounds = cls(
            left=float(mapping['left']),
            top=float(mapping['top']),
            right=float(mapping['right']),
            bottom=float(mapping['bottom']),
        )
        if bounds.right <= bounds.left or bounds.bottom <= bounds.top:
            raise ValueError('world_bounds must have right > left and bottom > top.')
        return bounds

    @property
    def width(self) -> float:
        return self.right - self.left

    @property
    def height(self) -> float:
        return self.bottom - self.top

    def clamp_entity_center(
        self,
        x: float,
        y: float,
        width: float,
        height: float,
    ) -> tuple[float, float]:
        """Keep an entity's whole AABB inside this world rectangle."""

        half_width = width * 0.5
        half_height = height * 0.5

        min_x = self.left + half_width
        max_x = self.right - half_width
        min_y = self.top + half_height
        max_y = self.bottom - half_height

        # A future stage may intentionally be smaller than one entity.
        # In that case, pin the entity to the bounds center on that axis.
        clamped_x = (self.left + self.right) * 0.5 if min_x > max_x else min(max(x, min_x), max_x)
        clamped_y = (self.top + self.bottom) * 0.5 if min_y > max_y else min(max(y, min_y), max_y)
        return clamped_x, clamped_y


class Camera:
    """Converts world positions to viewport positions.

    `view_left` and `view_top` are the world-space coordinates currently shown
    at the screen's top-left corner. Rendering converts world -> screen only at
    draw time; collision and gameplay never use this class.
    """

    def __init__(
        self,
        viewport_width: int,
        viewport_height: int,
        world_bounds: WorldBounds,
    ) -> None:
        self.viewport_width = int(viewport_width)
        self.viewport_height = int(viewport_height)
        self.world_bounds = world_bounds

        self.view_left = world_bounds.left
        self.view_top = world_bounds.top

    @property
    def view_right(self) -> float:
        return self.view_left + self.viewport_width

    @property
    def view_bottom(self) -> float:
        return self.view_top + self.viewport_height

    @property
    def center_x(self) -> float:
        return self.view_left + self.viewport_width * 0.5

    @property
    def center_y(self) -> float:
        return self.view_top + self.viewport_height * 0.5

    def snap_to_world_point(self, world_x: float, world_y: float) -> None:
        """Center the camera on a world point, clamped to stage bounds."""

        desired_left = world_x - self.viewport_width * 0.5
        desired_top = world_y - self.viewport_height * 0.5

        max_left = max(self.world_bounds.left, self.world_bounds.right - self.viewport_width)
        max_top = max(self.world_bounds.top, self.world_bounds.bottom - self.viewport_height)

        self.view_left = min(max(desired_left, self.world_bounds.left), max_left)
        self.view_top = min(max(desired_top, self.world_bounds.top), max_top)

    def follow(self, world_x: float, world_y: float) -> None:
        """Immediate follow for the prototype.

        A later smoothing/dead-zone camera belongs here, not in Player.
        """

        self.snap_to_world_point(world_x, world_y)

    def world_to_screen(self, world_x: float, world_y: float) -> tuple[int, int]:
        return (
            round(world_x - self.view_left),
            round(world_y - self.view_top),
        )

    def screen_to_world(self, screen_x: float, screen_y: float) -> tuple[float, float]:
        return (
            screen_x + self.view_left,
            screen_y + self.view_top,
        )

    def rect_from_world_center(
        self,
        world_x: float,
        world_y: float,
        width: float,
        height: float,
    ) -> pygame.Rect:
        screen_x, screen_y = self.world_to_screen(world_x, world_y)
        return pygame.Rect(
            round(screen_x - width * 0.5),
            round(screen_y - height * 0.5),
            round(width),
            round(height),
        )

    def is_world_rect_visible(
        self,
        world_x: float,
        world_y: float,
        width: float,
        height: float,
        *,
        padding: float = 0.0,
    ) -> bool:
        """Return whether a world-space center rectangle overlaps the viewport."""

        left = world_x - width * 0.5
        top = world_y - height * 0.5
        right = world_x + width * 0.5
        bottom = world_y + height * 0.5

        return not (
            right < self.view_left - padding
            or left > self.view_right + padding
            or bottom < self.view_top - padding
            or top > self.view_bottom + padding
        )
