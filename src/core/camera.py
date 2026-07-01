from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pygame


@dataclass(frozen=True)
class WorldBounds:
    """Playable rectangle in world coordinates.

    World coordinate convention:
    left-bottom = (0, 0)
    +x = right
    +y = up
    """

    left: float
    bottom: float
    right: float
    top: float

    @classmethod
    def from_mapping(cls, mapping: dict[str, Any]) -> WorldBounds:
        bounds = cls(
            left=float(mapping['left']),
            bottom=float(mapping['bottom']),
            right=float(mapping['right']),
            top=float(mapping['top']),
        )

        if bounds.right <= bounds.left or bounds.top <= bounds.bottom:
            raise ValueError(
                'world_bounds must have right > left and top > bottom.'
            )

        return bounds

    @property
    def width(self) -> float:
        return self.right - self.left

    @property
    def height(self) -> float:
        return self.top - self.bottom

    def clamp_entity_center(
        self,
        x: float,
        y: float,
        width: float,
        height: float,
    ) -> tuple[float, float]:
        half_width = width * 0.5
        half_height = height * 0.5

        min_x = self.left + half_width
        max_x = self.right - half_width

        min_y = self.bottom + half_height
        max_y = self.top - half_height

        clamped_x = (
            (self.left + self.right) * 0.5
            if min_x > max_x
            else min(max(x, min_x), max_x)
        )

        clamped_y = (
            (self.bottom + self.top) * 0.5
            if min_y > max_y
            else min(max(y, min_y), max_y)
        )

        return clamped_x, clamped_y


class Camera:
    """Converts world coordinates into pygame screen coordinates.

    World:
    - origin is bottom-left
    - y increases upward

    Pygame screen:
    - origin is top-left
    - y increases downward
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
        self.view_bottom = world_bounds.bottom

    @property
    def view_right(self) -> float:
        return self.view_left + self.viewport_width

    @property
    def view_top(self) -> float:
        return self.view_bottom + self.viewport_height

    @property
    def center_x(self) -> float:
        return self.view_left + self.viewport_width * 0.5

    @property
    def center_y(self) -> float:
        return self.view_bottom + self.viewport_height * 0.5

    def snap_to_world_point(
        self,
        world_x: float,
        world_y: float,
    ) -> None:
        desired_left = world_x - self.viewport_width * 0.5
        desired_bottom = world_y - self.viewport_height * 0.5

        max_left = max(
            self.world_bounds.left,
            self.world_bounds.right - self.viewport_width,
        )

        max_bottom = max(
            self.world_bounds.bottom,
            self.world_bounds.top - self.viewport_height,
        )

        self.view_left = min(
            max(desired_left, self.world_bounds.left),
            max_left,
        )

        self.view_bottom = min(
            max(desired_bottom, self.world_bounds.bottom),
            max_bottom,
        )

    def follow(self, world_x: float, world_y: float) -> None:
        self.snap_to_world_point(world_x, world_y)

    def world_to_screen(
        self,
        world_x: float,
        world_y: float,
    ) -> tuple[int, int]:
        """Convert world position to pygame screen position."""

        screen_x = world_x - self.view_left

        # World +Y is upward.
        # Screen +Y is downward.
        screen_y = self.viewport_height - (
            world_y - self.view_bottom
        )

        return round(screen_x), round(screen_y)

    def screen_to_world(
        self,
        screen_x: float,
        screen_y: float,
    ) -> tuple[float, float]:
        """Convert pygame screen position to world position."""

        world_x = screen_x + self.view_left

        world_y = self.view_bottom + (
            self.viewport_height - screen_y
        )

        return world_x, world_y

    def rect_from_world_center(
        self,
        world_x: float,
        world_y: float,
        width: float,
        height: float,
    ) -> pygame.Rect:
        screen_x, screen_y = self.world_to_screen(
            world_x,
            world_y,
        )

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
        left = world_x - width * 0.5
        bottom = world_y - height * 0.5
        right = world_x + width * 0.5
        top = world_y + height * 0.5

        return not (
            right < self.view_left - padding
            or left > self.view_right + padding
            or top < self.view_bottom - padding
            or bottom > self.view_top + padding
        )