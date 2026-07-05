from __future__ import annotations

from math import floor
from typing import TYPE_CHECKING, Iterable, Iterator

import pygame

from src.core.camera import Camera, WorldBounds
from src.core.collision import AABB, CollisionSystem
from src.core.navigation import (
    NavigationLane,
    StaticNavigationMap,
    build_static_navigation_map,
    make_profile,
    profile_key,
)

if TYPE_CHECKING:
    from src.app import GameApp
    from src.gameplay.entities.base import Entity
    from src.gameplay.entities.terrain import TerrainBlock


class World:
    """Owns runtime entities, collision groups, terrain lookups, and culling.

    The world keeps three independent indexes:
    - collision groups for gameplay categories;
    - terrain columns for local movement/navigation lookups;
    - a rebuilt broad-phase grid for collision checks among dynamic actors.

    Terrain and other static entities are not updated every frame. Their draw
    order is rebuilt only when entities are added or removed.
    """

    _TERRAIN_BOUNDARY_EPSILON = 1e-6
    _COLLISION_CELL_SIZE = 160.0

    # The active collision window is intentionally wider than every current
    # player projectile range (R93: 1,740 px) and enemy projectile range
    # (Stone Golem: 720 px). Objects beyond it cannot interact with the player
    # before their current lifetime ends, so they do not belong in this frame's
    # broad-phase grid.
    _DEFAULT_COLLISION_ACTIVITY_HALF_WIDTH = 2400.0
    _DEFAULT_COLLISION_ACTIVITY_HALF_HEIGHT = 900.0

    def __init__(self, bounds: WorldBounds) -> None:
        self.bounds = bounds
        self._entities: list[Entity] = []
        self._updatable_entities: list[Entity] = []
        self._pending_add: list[Entity] = []
        self._pending_remove: set[Entity] = set()
        self._groups: dict[str, list[Entity]] = {}

        # The stage configures this before it commits terrain blocks. A safe
        # default keeps World usable in small tests that do not configure it.
        self._terrain_tile_size = 40.0
        self._terrain_grid_origin_x = float(bounds.left)
        self._terrain_columns: dict[int, list[TerrainBlock]] = {}
        # Incremented whenever terrain topology changes. Navigation caches can
        # safely survive ordinary movement, but must be discarded if the stage
        # adds, removes, or rebuilds terrain.
        self._terrain_navigation_revision = 0

        # Static terrain is converted into profile-specific horizontal lanes.
        # They are built once after stage setup and invalidated only when terrain
        # topology actually changes.
        self._navigation_maps: dict[tuple[int, int], StaticNavigationMap] = {}
        self._player_navigation_lanes: dict[tuple[int, int], NavigationLane | None] = {}
        self._player_navigation_marker: tuple[float, float, bool, int] | None = None
        self._primary_player: Entity | None = None

        # Draw layers never depend on entity position, so sorting every render
        # frame is unnecessary. Terrain is stored separately because it is
        # culled by visible tile columns before drawing.
        self._draw_cache_dirty = True
        self._draw_layers: tuple[int, ...] = ()
        self._draw_non_terrain_by_layer: dict[int, tuple[Entity, ...]] = {}

        # Rebuilt after movement and before collision dispatch. The grid turns
        # projectile-versus-enemy checks from every-pair comparisons into local
        # neighbor checks.
        self._collision_cells: dict[
            str,
            dict[tuple[int, int], list[Entity]],
        ] = {}
        # A collider is immutable for the rest of a collision pass because the
        # index is rebuilt only after every entity has finished moving. Keeping
        # it here prevents every projectile-candidate comparison from creating
        # another short-lived AABB object.
        self._collision_aabbs: dict[Entity, AABB] = {}
        self._collision_activity_half_width = (
            self._DEFAULT_COLLISION_ACTIVITY_HALF_WIDTH
        )
        self._collision_activity_half_height = (
            self._DEFAULT_COLLISION_ACTIVITY_HALF_HEIGHT
        )
        self._collision_activity_center: tuple[float, float] | None = None

        # Enemy attacks are queued at the moment an enemy enters its attack
        # state. PlayScene drains only this list, avoiding a second full enemy
        # group scan every frame.
        self._enemy_attack_requests: list[tuple[Entity, str, int]] = []

        self.collisions = CollisionSystem()

    @property
    def terrain_tile_size(self) -> float:
        return self._terrain_tile_size

    @property
    def terrain_navigation_revision(self) -> int:
        """Monotonic revision for terrain-aware movement caches."""

        return self._terrain_navigation_revision

    def terrain_column_for_x(self, x: float) -> int:
        """Return the stage grid column containing a world x coordinate."""

        return self._terrain_column_for_x(x)

    def configure_collision_activity_window(
        self,
        *,
        half_width: float,
        half_height: float,
    ) -> None:
        """Configure the conservative player-centered collision activity area."""

        width = float(half_width)
        height = float(half_height)
        if width <= 0.0 or height <= 0.0:
            raise ValueError('collision activity dimensions must be positive.')

        self._collision_activity_half_width = width
        self._collision_activity_half_height = height

    def queue_enemy_attack(
        self,
        enemy: Entity,
        skill_id: str,
        direction: int,
    ) -> None:
        """Record an enemy projectile request without scanning every enemy."""

        if enemy.alive:
            self._enemy_attack_requests.append(
                (enemy, str(skill_id), 1 if direction >= 0 else -1)
            )

    def consume_enemy_attack_requests(
        self,
    ) -> list[tuple[Entity, str, int]]:
        """Return and clear attacks requested during the latest world update."""

        pending = self._enemy_attack_requests
        self._enemy_attack_requests = []
        return pending

    def configure_terrain_grid(self, tile_size: int | float) -> None:
        """Set the stage tile size used by terrain-navigation lookups."""

        value = float(tile_size)
        if value <= 0.0:
            raise ValueError('terrain tile size must be greater than zero.')

        self._terrain_tile_size = value
        self._terrain_grid_origin_x = float(self.bounds.left)
        self._terrain_columns.clear()
        self._terrain_navigation_revision += 1
        self._invalidate_static_navigation()

        for entity in self._groups.get('terrain', []):
            self._index_terrain_entity(entity)

    def add(self, entity: Entity) -> None:
        self._pending_add.append(entity)

    def remove(self, entity: Entity) -> None:
        entity.alive = False
        self._pending_remove.add(entity)

    def remove_all_in_group(self, group: str) -> None:
        """Queue removal for every current entity in one collision group.

        Player death uses this only for player_projectile so already-spawned
        attack effects are cancelled together with pending skill requests.
        """

        for entity in tuple(self._groups.get(group, ())):
            self.remove(entity)
        for entity in tuple(self._pending_add):
            if entity.collision_group == group:
                self.remove(entity)

    def commit(self) -> None:
        changed = False

        if self._pending_remove:
            removed = self._pending_remove
            self._entities = [
                entity
                for entity in self._entities
                if entity not in removed
            ]
            for entity in removed:
                self._unregister_entity(entity)
            self._pending_remove.clear()
            changed = True

        if self._pending_add:
            for entity in self._pending_add:
                # An entity can be spawned and removed in one frame. Keeping it
                # out of the indexes avoids dead entries and matches the useful
                # result of that sequence.
                if not entity.alive:
                    continue
                self._entities.append(entity)
                self._register_entity(entity)
                changed = True
            self._pending_add.clear()

        if changed:
            self._draw_cache_dirty = True

    def _register_entity(self, entity: Entity) -> None:
        if entity.updates_each_frame:
            self._updatable_entities.append(entity)

        group = entity.collision_group
        if group is None:
            return

        self._groups.setdefault(group, []).append(entity)
        if group == 'player' and self._primary_player is None:
            self._primary_player = entity
        if group == 'terrain':
            self._index_terrain_entity(entity)

    def _unregister_entity(self, entity: Entity) -> None:
        if entity.updates_each_frame:
            try:
                self._updatable_entities.remove(entity)
            except ValueError:
                pass

        group = entity.collision_group
        if group is None:
            return

        group_entities = self._groups.get(group)
        if group_entities is not None:
            try:
                group_entities.remove(entity)
            except ValueError:
                pass
            if not group_entities:
                self._groups.pop(group, None)

        if group == 'player' and entity is self._primary_player:
            self._primary_player = next(
                (
                    candidate
                    for candidate in self._groups.get('player', ())
                    if candidate.alive
                ),
                None,
            )
            self._player_navigation_marker = None
            self._player_navigation_lanes.clear()

        if group == 'terrain':
            self._unindex_terrain_entity(entity)

    def _terrain_column_for_x(self, x: float) -> int:
        return floor(
            (float(x) - self._terrain_grid_origin_x)
            / self._terrain_tile_size
        )

    def _terrain_column_for_entity(self, entity: Entity) -> int:
        grid_col = getattr(entity, 'grid_col', None)
        if isinstance(grid_col, int):
            return grid_col
        return self._terrain_column_for_x(entity.x)

    def _index_terrain_entity(self, entity: Entity) -> None:
        column = self._terrain_column_for_entity(entity)
        self._terrain_columns.setdefault(column, []).append(entity)
        self._terrain_navigation_revision += 1
        self._invalidate_static_navigation()

    def _unindex_terrain_entity(self, entity: Entity) -> None:
        column = self._terrain_column_for_entity(entity)
        blocks = self._terrain_columns.get(column)
        if blocks is None:
            return

        try:
            blocks.remove(entity)
        except ValueError:
            return

        if not blocks:
            self._terrain_columns.pop(column, None)
        self._terrain_navigation_revision += 1
        self._invalidate_static_navigation()

    def terrain_blocks_at_x(self, x: float) -> Iterable[TerrainBlock]:
        """Return only terrain in the tile column containing ``x``.

        At an exact tile seam both touching columns are returned. This preserves
        the old inclusive edge behavior while avoiding a full terrain scan.
        """

        column = self._terrain_column_for_x(x)
        primary = self._terrain_columns.get(column, ())
        local_x = (
            float(x) - self._terrain_grid_origin_x
            - column * self._terrain_tile_size
        )
        if abs(local_x) <= self._TERRAIN_BOUNDARY_EPSILON:
            previous = self._terrain_columns.get(column - 1, ())
            if previous:
                return (*previous, *primary)
        return primary

    def terrain_blocks_overlapping_x(
        self,
        left: float,
        right: float,
    ) -> Iterator[TerrainBlock]:
        """Yield terrain blocks in columns overlapping a horizontal AABB."""

        first_column = self._terrain_column_for_x(left)
        # Right edges are exclusive for AABB intersection, so an exact seam
        # must not pull in the next column.
        adjusted_right = max(left, right - self._TERRAIN_BOUNDARY_EPSILON)
        last_column = self._terrain_column_for_x(adjusted_right)

        for column in range(first_column, last_column + 1):
            yield from self._terrain_columns.get(column, ())

    # ------------------------------------------------------------------
    # Static navigation lanes

    @property
    def primary_player(self) -> Entity | None:
        """Return the cached live player without scanning its group per enemy."""

        player = self._primary_player
        if player is not None and player.alive:
            return player

        player = self.first_with_group('player')
        self._primary_player = player
        return player

    def _invalidate_static_navigation(self) -> None:
        self._navigation_maps.clear()
        self._player_navigation_lanes.clear()
        self._player_navigation_marker = None

    def prepare_navigation_profile(
        self,
        width: float,
        height: float,
    ) -> StaticNavigationMap:
        """Return a stage-static navigation map for one collider size."""

        key = profile_key(width, height)
        cached = self._navigation_maps.get(key)
        if (
            cached is not None
            and cached.terrain_revision == self._terrain_navigation_revision
        ):
            return cached

        navigation_map = build_static_navigation_map(
            self._terrain_columns,
            tile_size=self._terrain_tile_size,
            origin_x=self._terrain_grid_origin_x,
            terrain_revision=self._terrain_navigation_revision,
            profile=make_profile(width, height),
            epsilon=self._TERRAIN_BOUNDARY_EPSILON,
        )
        self._navigation_maps[key] = navigation_map
        self._player_navigation_marker = None
        self._player_navigation_lanes.pop(key, None)
        return navigation_map

    def navigation_lane_for_body(
        self,
        *,
        x: float,
        body_bottom: float,
        width: float,
        height: float,
        allow_spawn_tolerance: bool = False,
    ) -> NavigationLane | None:
        """Resolve a prebuilt lane; this never scans terrain at runtime."""

        navigation_map = self.prepare_navigation_profile(width, height)
        tolerance = self._terrain_tile_size * (0.5 if allow_spawn_tolerance else 0.15)
        if allow_spawn_tolerance:
            return navigation_map.nearest_lane_at_spawn(
                x,
                body_bottom,
                vertical_tolerance=tolerance,
                epsilon=self._TERRAIN_BOUNDARY_EPSILON,
            )
        return navigation_map.lane_at(
            x,
            body_bottom,
            vertical_tolerance=tolerance,
            epsilon=self._TERRAIN_BOUNDARY_EPSILON,
        )

    def _refresh_player_navigation_lanes(self) -> None:
        player = self.primary_player
        if player is None:
            marker = (0.0, 0.0, False, self._terrain_navigation_revision)
            if marker != self._player_navigation_marker:
                self._player_navigation_lanes = {
                    key: None for key in self._navigation_maps
                }
                self._player_navigation_marker = marker
            return

        # An airborne player has no horizontal walking lane. The last grounded
        # lane is deliberately not reused: enemies without jump/fall movement
        # must not chase a target in mid-air.
        grounded = bool(getattr(player, 'is_grounded', True))
        body_bottom = float(getattr(player, 'bottom', player.y - player.height * 0.5))
        marker = (
            float(player.x),
            body_bottom,
            grounded,
            self._terrain_navigation_revision,
        )
        if marker == self._player_navigation_marker:
            return

        refreshed: dict[tuple[int, int], NavigationLane | None] = {}
        if grounded:
            for key, navigation_map in self._navigation_maps.items():
                refreshed[key] = navigation_map.lane_at(
                    player.x,
                    body_bottom,
                    vertical_tolerance=self._terrain_tile_size * 0.15,
                    epsilon=self._TERRAIN_BOUNDARY_EPSILON,
                )
        else:
            refreshed = {key: None for key in self._navigation_maps}

        self._player_navigation_lanes = refreshed
        self._player_navigation_marker = marker

    def player_navigation_lane_id_for_profile(
        self,
        width: float,
        height: float,
    ) -> int | None:
        """Return the player's current lane for an enemy collider profile."""

        key = profile_key(width, height)
        self.prepare_navigation_profile(width, height)
        self._refresh_player_navigation_lanes()
        lane = self._player_navigation_lanes.get(key)
        return None if lane is None else lane.lane_id

    # ------------------------------------------------------------------
    # Collision broad phase

    def _refresh_collision_activity_center(self) -> None:
        # ``primary_player`` is maintained on add/remove, so this avoids a
        # repeated group scan whenever the collision grid is rebuilt.
        player = self.primary_player
        if player is None:
            self._collision_activity_center = None
            return
        self._collision_activity_center = (player.x, player.y)

    def is_collision_active(self, entity: Entity) -> bool:
        """Whether an entity can still collide in the current player window."""

        if entity.collision_group == 'player':
            return True

        center = self._collision_activity_center
        if center is None:
            # Small test worlds or menu scenes may not have a player.
            return True

        center_x, center_y = center
        half_width = entity.width * 0.5
        half_height = entity.height * 0.5
        return not (
            entity.x + half_width < center_x - self._collision_activity_half_width
            or entity.x - half_width > center_x + self._collision_activity_half_width
            or entity.y + half_height < center_y - self._collision_activity_half_height
            or entity.y - half_height > center_y + self._collision_activity_half_height
        )

    def _collision_cell_range(
        self,
        collider: AABB,
    ) -> tuple[int, int, int, int]:
        cell_size = self._COLLISION_CELL_SIZE
        left = floor(collider.left / cell_size)
        right = floor(
            (collider.right - self._TERRAIN_BOUNDARY_EPSILON) / cell_size
        )
        bottom = floor(collider.bottom / cell_size)
        top = floor(
            (collider.top - self._TERRAIN_BOUNDARY_EPSILON) / cell_size
        )
        return left, right, bottom, top

    def rebuild_collision_index(self, groups: Iterable[str]) -> None:
        """Build a frame-local spatial hash only for registered rule groups."""

        self._collision_cells.clear()
        self._collision_aabbs.clear()
        self._refresh_collision_activity_center()

        # CollisionSystem already supplies unique group names. Do not build a
        # second temporary set here every frame.
        for group in groups:
            cells: dict[tuple[int, int], list[Entity]] = {}
            for entity in self._groups.get(group, ()):
                if not entity.alive or not self.is_collision_active(entity):
                    continue

                collider = entity.get_aabb()
                if collider is None:
                    continue

                self._collision_aabbs[entity] = collider
                left, right, bottom, top = self._collision_cell_range(collider)
                for column in range(left, right + 1):
                    for row in range(bottom, top + 1):
                        cells.setdefault((column, row), []).append(entity)

            self._collision_cells[group] = cells

    def collision_aabb(self, entity: Entity) -> AABB | None:
        """Return this pass's collider without allocating a second AABB.

        CollisionSystem calls this after :meth:`rebuild_collision_index`, when
        movement is already complete. The fallback keeps the method safe for
        focused unit tests that call it outside that normal frame sequence.
        """

        cached = self._collision_aabbs.get(entity)
        if cached is not None:
            return cached
        return entity.get_aabb()

    def collision_candidates(
        self,
        group: str,
        collider: AABB,
    ) -> Iterator[Entity]:
        """Yield each potentially overlapping entity once from nearby cells."""

        cells = self._collision_cells.get(group)
        if cells is None:
            yield from self._groups.get(group, ())
            return

        left, right, bottom, top = self._collision_cell_range(collider)

        # Most bullets and small actors fit entirely in one grid cell. In that
        # case every list entry is inherently unique, so a per-query ``set`` is
        # needless allocation work during rapid fire.
        if left == right and bottom == top:
            yield from cells.get((left, bottom), ())
            return

        # Larger colliders may occupy several cells. Preserve the original
        # exactly-once semantics only for this less common path.
        seen: set[int] = set()
        for column in range(left, right + 1):
            for row in range(bottom, top + 1):
                for entity in cells.get((column, row), ()):
                    entity_id = id(entity)
                    if entity_id in seen:
                        continue
                    seen.add(entity_id)
                    yield entity

    # ------------------------------------------------------------------
    # Update and rendering

    def update(self, delta_seconds: float, app: GameApp) -> None:
        self.commit()

        # The player is advanced first. Static navigation then resolves the
        # player's lane once for every distinct enemy collider profile; every
        # enemy merely reads that cached lane id during its AI step.
        for entity in self._updatable_entities:
            if entity.alive and entity.collision_group == 'player':
                entity.update(delta_seconds, self, app)

        self._refresh_player_navigation_lanes()

        # Static terrain, items, and portals never enter this list. Pending
        # add/remove operations are committed after the loop, so iterating the
        # stable list directly avoids allocating a tuple every frame.
        for entity in self._updatable_entities:
            if entity.alive and entity.collision_group != 'player':
                entity.update(delta_seconds, self, app)

        self.commit()
        self.collisions.check(self, app)
        self.commit()

    def _rebuild_draw_cache(self) -> None:
        layers: set[int] = set()
        non_terrain_by_layer: dict[int, list[Entity]] = {}

        for entity in self._entities:
            layers.add(entity.layer)
            if entity.collision_group == 'terrain':
                continue
            non_terrain_by_layer.setdefault(entity.layer, []).append(entity)

        self._draw_layers = tuple(sorted(layers))
        self._draw_non_terrain_by_layer = {
            layer: tuple(entities)
            for layer, entities in non_terrain_by_layer.items()
        }
        self._draw_cache_dirty = False

    def _visible_terrain_by_layer(
        self,
        camera: Camera,
    ) -> dict[int, list[Entity]]:
        """Return only terrain tiles inside the camera's horizontal columns."""

        first_column = self._terrain_column_for_x(camera.view_left)
        last_column = self._terrain_column_for_x(
            camera.view_right - self._TERRAIN_BOUNDARY_EPSILON
        )
        visible: dict[int, list[Entity]] = {}

        for column in range(first_column, last_column + 1):
            for entity in self._terrain_columns.get(column, ()):
                if not entity.alive:
                    continue
                if not camera.is_world_rect_visible(
                    entity.x,
                    entity.y,
                    entity.width,
                    entity.height,
                ):
                    continue
                visible.setdefault(entity.layer, []).append(entity)

        return visible

    def draw(self, screen: pygame.Surface, app: GameApp, camera: Camera) -> None:
        if self._draw_cache_dirty:
            self._rebuild_draw_cache()

        visible_terrain = self._visible_terrain_by_layer(camera)
        visible_entities: list[Entity] = []

        # Terrain is always submitted only from visible tile columns. The
        # existing stage layers place terrain below portals/items/projectiles/
        # actors, and the same layer ordering is retained here.
        for layer in self._draw_layers:
            terrain_blits: list[tuple[pygame.Surface, tuple[int, int]]] = []
            for entity in visible_terrain.get(layer, ()):
                if bool(getattr(entity, 'is_visual_hidden', False)):
                    continue

                # TerrainBlock supplies an already-cached source surface and
                # destination pair. One native blits call reduces Python-to-SDL
                # draw-call overhead when a camera sees many tile blocks.
                draw_command = getattr(entity, 'draw_command', None)
                if callable(draw_command):
                    terrain_blits.append(draw_command(app, camera))
                else:
                    # Preserve World compatibility with alternate terrain
                    # entities that expose only the standard Entity.draw API.
                    entity.draw(screen, self, app, camera)
                visible_entities.append(entity)

            if terrain_blits:
                screen.blits(terrain_blits, False)

            for entity in self._draw_non_terrain_by_layer.get(layer, ()):
                if not entity.alive or bool(
                    getattr(entity, 'is_visual_hidden', False)
                ):
                    continue
                entity.draw(screen, self, app, camera)
                visible_entities.append(entity)

        # Debug layers are deliberately ordered:
        # 1) enemy detection rectangles (green)
        # 2) enemy skill / attack rectangles (orange)
        # 3) every actor's actual collision AABB (red)
        if app.debug_draw_actor_bounds:
            for entity in visible_entities:
                draw_ranges = getattr(entity, 'draw_debug_ranges', None)
                if callable(draw_ranges):
                    draw_ranges(screen, camera)

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

        # Red collision AABB: horizontally centered at entity.x, vertically
        # defined from its physical bottom upward. The rectangle is equivalent
        # to using entity.y, but this makes its convention match green/orange.
        center_y = entity.bottom + entity.height * 0.5
        rect = camera.rect_from_world_center(
            entity.x,
            center_y,
            entity.width,
            entity.height,
        )
        pygame.draw.rect(screen, (255, 0, 0), rect, width=2)

    def entities_with_group(self, group: str) -> Iterable[Entity]:
        """Return the indexed group; callers must not mutate the result."""

        return self._groups.get(group, ())

    def first_with_group(self, group: str) -> Entity | None:
        for entity in self._groups.get(group, ()):
            if entity.alive:
                return entity
        return None
