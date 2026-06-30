from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pygame

from src.gameplay.entities.base import Entity

if TYPE_CHECKING:
    from src.app import GameApp
    from src.core.camera import Camera
    from src.core.world import World


class Player(Entity):
    """Runtime player state.

    All position and movement values are WORLD coordinates. The Camera is used
    only in draw(), so camera scrolling can never affect collision or speed.
    """

    def __init__(self, character_id: str, definition: dict[str, Any], x: float, y: float) -> None:
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
        self.max_hp = int(stats['max_hp'])
        self.hp = self.max_hp
        self.move_speed = float(stats['move_speed'])

        self.skill_ids: list[str] = list(definition['starting_loadout']['skill_ids'])
        self.inventory: dict[str, int] = dict(definition['starting_loadout']['items'])
        self._cooldown_ready_at: dict[str, float] = {}

        self._left_held = False
        self._right_held = False
        self.facing = 1

    def handle_event(self, event: pygame.event.Event, app: GameApp) -> str | None:
        if event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_a, pygame.K_LEFT):
                self._left_held = True
            elif event.key in (pygame.K_d, pygame.K_RIGHT):
                self._right_held = True
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

    def try_use_skill(self, slot_index: int, app: GameApp) -> str | None:
        if slot_index >= len(self.skill_ids):
            return None

        skill_id = self.skill_ids[slot_index]
        skill = app.data.record('skills', skill_id)
        now = app.timer.game_time
        ready_at = self._cooldown_ready_at.get(skill_id, 0.0)

        if now < ready_at:
            remaining = ready_at - now
            return f"{skill['display_name']} 재사용 대기: {remaining:.1f}초"

        self._cooldown_ready_at[skill_id] = now + float(skill['cooldown_seconds'])
        return skill_id

    def add_item(self, item_id: str, amount: int, item_definition: dict[str, Any]) -> str:
        current = self.inventory.get(item_id, 0)
        maximum = int(item_definition['max_stack'])
        accepted = max(0, min(amount, maximum - current))
        self.inventory[item_id] = current + accepted

        if accepted == 0:
            return f"{item_definition['display_name']}은(는) 더 들 수 없습니다."
        return f"{item_definition['display_name']} +{accepted}"

    def update(self, delta_seconds: float, world: World, app: GameApp) -> None:
        direction = int(self._right_held) - int(self._left_held)
        if direction != 0:
            self.facing = direction
            self.x += direction * self.move_speed * delta_seconds

        # World bounds are stage data. No screen-width constant belongs here.
        self.x, self.y = world.bounds.clamp_entity_center(
            self.x,
            self.y,
            self.width,
            self.height,
        )

    def draw(
        self,
        screen: pygame.Surface,
        world: World,
        app: GameApp,
        camera: Camera,
    ) -> None:
        if not camera.is_world_rect_visible(self.x, self.y, self.width, self.height):
            return

        rect = camera.rect_from_world_center(self.x, self.y, self.width, self.height)
        pygame.draw.rect(screen, self.color, rect, border_radius=6)
        pygame.draw.rect(screen, (224, 240, 255), rect, width=2, border_radius=6)
