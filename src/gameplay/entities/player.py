from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pygame

from src.gameplay.entities.base import Entity
from src.gameplay.entities.terrain import TerrainBlock

if TYPE_CHECKING:
    from src.app import GameApp
    from src.core.camera import Camera
    from src.core.world import World


class Player(Entity):
    """Player movement using bottom-left world coordinates."""

    _COLLISION_EPSILON = 0.001

    def __init__(
        self,
        character_id: str,
        definition: dict[str, Any],
        x: float,
        y: float,
    ) -> None:
        visual = definition['visual']

        super().__init__(
            x=x,
            y=y,
            width=float(visual['width']),
            height=float(visual['height']),
            layer=20,
            collision_group='player',
        )

        self.character_id = character_id
        self.display_name = definition['display_name']
        self.color = tuple(visual['placeholder_color'])

        stats = definition['stats']
        movement = definition['movement']

        self.max_hp = int(stats['max_hp'])
        self.hp = self.max_hp

        self.move_speed = float(stats['move_speed'])
        self.gravity = float(movement['gravity'])
        self.jump_speed = float(movement['jump_speed'])
        self.max_fall_speed = float(movement['max_fall_speed'])

        self.skill_ids: list[str] = list(
            definition['starting_loadout']['skill_ids']
        )

        self.inventory: dict[str, int] = dict(
            definition['starting_loadout']['items']
        )

        self._cooldown_ready_at: dict[str, float] = {}

        self._left_held = False
        self._right_held = False
        self._jump_requested = False

        self.velocity_y = 0.0
        self.is_grounded = False
        self.facing = 1

    @property
    def left(self) -> float:
        return self.x - self.width * 0.5

    @property
    def right(self) -> float:
        return self.x + self.width * 0.5

    @property
    def bottom(self) -> float:
        return self.y - self.height * 0.5

    @property
    def top(self) -> float:
        return self.y + self.height * 0.5

    def handle_event(
        self,
        event: pygame.event.Event,
        app: GameApp,
    ) -> str | None:
        if event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_a, pygame.K_LEFT):
                self._left_held = True

            elif event.key in (pygame.K_d, pygame.K_RIGHT):
                self._right_held = True

            elif event.key in (pygame.K_UP, pygame.K_SPACE):
                self._jump_requested = True

            elif event.key == pygame.K_1:
                return self.try_use_skill(0, app)

            elif event.key == pygame.K_2:
                return self.try_use_skill(1, app)

        elif event.type == pygame.KEYUP:
            if event.key in (pygame.K_a, pygame.K_LEFT):
                self._left_held = False

            elif event.key in (pygame.K_d, pygame.K_RIGHT):
                self._right_held = False

        return None

    def try_use_skill(
        self,
        slot_index: int,
        app: GameApp,
    ) -> str | None:
        if slot_index >= len(self.skill_ids):
            return None

        skill_id = self.skill_ids[slot_index]
        skill = app.data.record('skills', skill_id)

        now = app.timer.game_time
        ready_at = self._cooldown_ready_at.get(skill_id, 0.0)

        if now < ready_at:
            remaining = ready_at - now
            return (
                f"{skill['display_name']} 재사용 대기: "
                f'{remaining:.1f}초'
            )

        self._cooldown_ready_at[skill_id] = (
            now + float(skill['cooldown_seconds'])
        )

        return skill_id

    def add_item(
        self,
        item_id: str,
        amount: int,
        item_definition: dict[str, Any],
    ) -> str:
        current = self.inventory.get(item_id, 0)
        maximum = int(item_definition['max_stack'])

        accepted = max(
            0,
            min(amount, maximum - current),
        )

        self.inventory[item_id] = current + accepted

        if accepted == 0:
            return (
                f"{item_definition['display_name']}은(는) "
                '더 들 수 없습니다.'
            )

        return f"{item_definition['display_name']} +{accepted}"

    def update(
        self,
        delta_seconds: float,
        world: World,
        app: GameApp,
    ) -> None:
        terrain = tuple(
            entity
            for entity in world.entities_with_group('terrain')
            if isinstance(entity, TerrainBlock)
        )

        direction = (
            int(self._right_held)
            - int(self._left_held)
        )

        if direction != 0:
            self.facing = direction

            self._move_horizontally(
                direction * self.move_speed * delta_seconds,
                terrain,
            )

        if self._jump_requested and self.is_grounded:
            self.velocity_y = self.jump_speed
            self.is_grounded = False

        self._jump_requested = False

        self._move_vertically(
            delta_seconds,
            terrain,
        )

        self._clamp_to_world_bounds(world)

    def _move_horizontally(
        self,
        movement_x: float,
        terrain: tuple[TerrainBlock, ...],
    ) -> None:
        if movement_x == 0.0:
            return

        previous_left = self.left
        previous_right = self.right

        self.x += movement_x

        for block in terrain:
            if not block.is_solid:
                continue

            if not self._vertical_overlaps(block):
                continue

            if movement_x > 0.0:
                crossed_left_side = (
                    previous_right
                    <= block.left + self._COLLISION_EPSILON
                    and self.right > block.left
                )

                if crossed_left_side:
                    self.x = block.left - self.width * 0.5

            else:
                crossed_right_side = (
                    previous_left
                    >= block.right - self._COLLISION_EPSILON
                    and self.left < block.right
                )

                if crossed_right_side:
                    self.x = block.right + self.width * 0.5

    def _move_vertically(
        self,
        delta_seconds: float,
        terrain: tuple[TerrainBlock, ...],
    ) -> None:
        previous_top = self.top
        previous_bottom = self.bottom

        # In bottom-left coordinates gravity pulls downward.
        self.velocity_y = max(
            self.velocity_y - self.gravity * delta_seconds,
            -self.max_fall_speed,
        )

        self.y += self.velocity_y * delta_seconds
        self.is_grounded = False

        if self.velocity_y <= 0.0:
            self._resolve_landing(
                previous_bottom,
                terrain,
            )
        else:
            self._resolve_ceiling(
                previous_top,
                terrain,
            )

    def _resolve_landing(
        self,
        previous_bottom: float,
        terrain: tuple[TerrainBlock, ...],
    ) -> None:
        landing_block: TerrainBlock | None = None

        for block in terrain:
            if not (block.is_solid or block.is_one_way):
                continue

            if not self._horizontal_overlaps(block):
                continue

            crossed_top = (
                previous_bottom
                >= block.top - self._COLLISION_EPSILON
                and self.bottom <= block.top
            )

            if not crossed_top:
                continue

            # Choose the highest surface reached during this fall.
            if (
                landing_block is None
                or block.top > landing_block.top
            ):
                landing_block = block

        if landing_block is not None:
            self.y = (
                landing_block.top
                + self.height * 0.5
            )

            self.velocity_y = 0.0
            self.is_grounded = True

    def _resolve_ceiling(
        self,
        previous_top: float,
        terrain: tuple[TerrainBlock, ...],
    ) -> None:
        ceiling_block: TerrainBlock | None = None

        for block in terrain:
            if not block.is_solid:
                continue

            if not self._horizontal_overlaps(block):
                continue

            crossed_bottom = (
                previous_top
                <= block.bottom + self._COLLISION_EPSILON
                and self.top >= block.bottom
            )

            if not crossed_bottom:
                continue

            # Choose the lowest ceiling reached while moving upward.
            if (
                ceiling_block is None
                or block.bottom < ceiling_block.bottom
            ):
                ceiling_block = block

        if ceiling_block is not None:
            self.y = (
                ceiling_block.bottom
                - self.height * 0.5
            )

            self.velocity_y = 0.0

    def _vertical_overlaps(
        self,
        block: TerrainBlock,
    ) -> bool:
        return (
            self.top > block.bottom
            and self.bottom < block.top
        )

    def _horizontal_overlaps(
        self,
        block: TerrainBlock,
    ) -> bool:
        return (
            self.right > block.left
            and self.left < block.right
        )

    def _clamp_to_world_bounds(
        self,
        world: World,
    ) -> None:
        bounds = world.bounds

        half_width = self.width * 0.5
        half_height = self.height * 0.5

        if self.left < bounds.left:
            self.x = bounds.left + half_width

        elif self.right > bounds.right:
            self.x = bounds.right - half_width

        # World bottom is the fail-safe floor.
        if self.bottom < bounds.bottom:
            self.y = bounds.bottom + half_height

            if self.velocity_y < 0.0:
                self.velocity_y = 0.0

            self.is_grounded = True

        # World top is the fail-safe ceiling.
        if self.top > bounds.top:
            self.y = bounds.top - half_height

            if self.velocity_y > 0.0:
                self.velocity_y = 0.0

    def draw(
        self,
        screen: pygame.Surface,
        world: World,
        app: GameApp,
        camera: Camera,
    ) -> None:
        if not camera.is_world_rect_visible(
            self.x,
            self.y,
            self.width,
            self.height,
        ):
            return

        rect = camera.rect_from_world_center(
            self.x,
            self.y,
            self.width,
            self.height,
        )

        pygame.draw.rect(
            screen,
            self.color,
            rect,
            border_radius=6,
        )

        pygame.draw.rect(
            screen,
            (224, 240, 255),
            rect,
            width=2,
            border_radius=6,
        )