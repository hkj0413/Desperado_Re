from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from math import floor
from typing import Iterable, Mapping, Protocol


class TerrainLike(Protocol):
    """Minimal terrain shape required by the static lane builder."""

    left: float
    right: float
    bottom: float
    top: float
    is_solid: bool
    is_one_way: bool


ProfileKey = tuple[int, int]


@dataclass(frozen=True, slots=True)
class NavigationProfile:
    """Collision dimensions used to build lanes for one walker type."""

    key: ProfileKey
    width: float
    height: float


@dataclass(frozen=True, slots=True)
class NavigationLane:
    """One continuous horizontal route that a specific collider can occupy."""

    lane_id: int
    surface_top: float
    center_left: float
    center_right: float
    first_column: int
    last_column: int

    def contains_x(self, x: float, *, epsilon: float = 1e-6) -> bool:
        return self.center_left - epsilon <= x <= self.center_right + epsilon


@dataclass(slots=True)
class StaticNavigationMap:
    """Precomputed flat walking lanes for a collider profile and terrain revision."""

    profile: NavigationProfile
    terrain_revision: int
    tile_size: float
    origin_x: float
    lanes: tuple[NavigationLane, ...]
    lanes_by_column: dict[int, tuple[NavigationLane, ...]]

    def lane_at(
        self,
        x: float,
        surface_top: float,
        *,
        vertical_tolerance: float,
        epsilon: float = 1e-6,
    ) -> NavigationLane | None:
        """Return the lane occupying this exact point, without terrain scanning."""

        column = floor((float(x) - self.origin_x) / self.tile_size)
        for lane in self.lanes_by_column.get(column, ()):
            if abs(lane.surface_top - surface_top) > vertical_tolerance:
                continue
            if lane.contains_x(x, epsilon=epsilon):
                return lane
        return None

    def nearest_lane_at_spawn(
        self,
        x: float,
        body_bottom: float,
        *,
        vertical_tolerance: float,
        epsilon: float = 1e-6,
    ) -> NavigationLane | None:
        """Find a lane for stage validation; prefers the closest matching surface."""

        column = floor((float(x) - self.origin_x) / self.tile_size)
        candidates = [
            lane
            for lane in self.lanes_by_column.get(column, ())
            if lane.contains_x(x, epsilon=epsilon)
            and abs(lane.surface_top - body_bottom) <= vertical_tolerance
        ]
        if not candidates:
            return None
        return min(candidates, key=lambda lane: abs(lane.surface_top - body_bottom))


def profile_key(width: float, height: float) -> ProfileKey:
    """Use integer thousandths so equivalent float collider sizes share a map."""

    return (round(float(width) * 1000.0), round(float(height) * 1000.0))


def make_profile(width: float, height: float) -> NavigationProfile:
    return NavigationProfile(
        key=profile_key(width, height),
        width=max(0.0, float(width)),
        height=max(0.0, float(height)),
    )


def build_static_navigation_map(
    terrain_columns: Mapping[int, Iterable[TerrainLike]],
    *,
    tile_size: float,
    origin_x: float,
    terrain_revision: int,
    profile: NavigationProfile,
    epsilon: float = 1e-6,
) -> StaticNavigationMap:
    """Build all flat lanes once from immutable tile terrain.

    A lane is formed only where every tile column provides a support top at the
    same height and no *solid* tile intersects the walker's body volume. One-way
    platforms support a lane but do not behave as side walls, matching the
    player's existing collision rules.
    """

    tile_size = max(float(tile_size), epsilon)
    columns = {
        int(column): tuple(blocks)
        for column, blocks in terrain_columns.items()
        if blocks
    }
    if not columns:
        return StaticNavigationMap(
            profile=profile,
            terrain_revision=terrain_revision,
            tile_size=tile_size,
            origin_x=float(origin_x),
            lanes=(),
            lanes_by_column={},
        )

    support_columns_by_top: dict[float, set[int]] = defaultdict(set)
    for column, blocks in columns.items():
        for block in blocks:
            if not (block.is_solid or block.is_one_way):
                continue
            support_columns_by_top[round(float(block.top), 6)].add(column)

    first_stage_column = min(columns)
    last_stage_column = max(columns)
    half_width = profile.width * 0.5
    lanes: list[NavigationLane] = []
    lanes_by_column: dict[int, list[NavigationLane]] = defaultdict(list)
    next_lane_id = 0

    def column_blocks_body(column: int, surface_top: float) -> bool:
        body_bottom = surface_top
        body_top = surface_top + profile.height
        for block in columns.get(column, ()):
            if not block.is_solid:
                continue
            # The supporting tile itself ends at body_bottom and is allowed.
            if (
                float(block.top) > body_bottom + epsilon
                and float(block.bottom) < body_top - epsilon
            ):
                return True
        return False

    for surface_top, support_columns in support_columns_by_top.items():
        run_start: int | None = None
        for column in range(first_stage_column, last_stage_column + 2):
            usable = (
                column in support_columns
                and not column_blocks_body(column, surface_top)
            )
            if usable:
                if run_start is None:
                    run_start = column
                continue

            if run_start is None:
                continue

            run_end = column - 1
            raw_left = float(origin_x) + run_start * tile_size
            raw_right = float(origin_x) + (run_end + 1) * tile_size
            center_left = raw_left + half_width
            center_right = raw_right - half_width
            if center_right + epsilon >= center_left:
                lane = NavigationLane(
                    lane_id=next_lane_id,
                    surface_top=float(surface_top),
                    center_left=center_left,
                    center_right=center_right,
                    first_column=run_start,
                    last_column=run_end,
                )
                lanes.append(lane)
                for lane_column in range(run_start, run_end + 1):
                    lanes_by_column[lane_column].append(lane)
                next_lane_id += 1

            run_start = None

    return StaticNavigationMap(
        profile=profile,
        terrain_revision=terrain_revision,
        tile_size=tile_size,
        origin_x=float(origin_x),
        lanes=tuple(lanes),
        lanes_by_column={
            column: tuple(column_lanes)
            for column, column_lanes in lanes_by_column.items()
        },
    )
