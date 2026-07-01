from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pygame

from src.gameplay.character_assets import CharacterSpriteCache
from src.gameplay.entities.base import Entity
from src.gameplay.entities.terrain import TerrainBlock
from src.gameplay.party import CharacterActionState, PartyManager

if TYPE_CHECKING:
    from src.app import GameApp
    from src.core.camera import Camera
    from src.core.world import World


class Player(Entity):
    """The currently active party member in the world.

    Shared by the selected pair:
    - HP, experience, level, enhancement
    - normal item inventory / hotbar and item cooldowns

    Kept separately by each character:
    - ammunition
    - skill cooldowns
    - move speed and attack-speed multiplier
    - attack-speed multiplier
    - animation and action state

    The party shares its facing direction, so movement, attack, and skill aim
    remain consistent when main/sub members are swapped.
    """

    _COLLISION_EPSILON = 0.001
    _ACTION_ALLOWED_STATES = frozenset(('idle', 'walk'))
    _SWAP_ALLOWED_STATES = frozenset(('idle', 'walk'))
    _DASH_CANCEL_ALLOWED_STATES = frozenset(
        ('idle', 'walk', 'jump', 'fall', 'attack', 'skill', 'hit')
    )
    _ABILITY_FIELD_BY_BINDING = {
        'basic': 'basic_attack_id',
        'skill_s': 'skill_s_id',
        'skill_d': 'skill_d_id',
        'main_unique': 'main_unique_skill_id',
        'main_ultimate': 'main_ultimate_skill_id',
    }

    def __init__(
        self,
        party: PartyManager,
        x: float,
        y: float,
    ) -> None:
        self.party = party
        self._definition = party.active_definition
        collider = party.shared_settings['collider']

        super().__init__(
            x=x,
            y=y,
            width=float(collider['width']),
            height=float(collider['height']),
            layer=20,
            collision_group='player',
        )

        self._left_held = False
        self._right_held = False
        self._jump_requested = False
        self._basic_attack_held = False
        self.velocity_y = 0.0
        self.is_grounded = False

        # The initial stage spawn is the party-wide respawn destination.
        self._respawn_x = float(x)
        self._respawn_y = float(y)

        # PlayScene drains this list and spawns actual projectile entities.
        # Player owns input/timing/state; the scene owns adding world entities.
        self._pending_skill_ids: list[str] = []

        self._apply_active_character_definition()

    @property
    def character_id(self) -> str:
        return self.party.active_character_id

    @property
    def display_name(self) -> str:
        return str(self._definition['display_name'])

    @property
    def hp(self) -> int:
        return self.party.shared_hp

    @property
    def max_hp(self) -> int:
        return self.party.max_hp

    @property
    def experience(self) -> int:
        return self.party.shared_experience

    @property
    def inventory(self) -> dict[str, int]:
        return self.party.shared_inventory

    @property
    def ammo(self) -> dict[str, int]:
        return self.party.active_runtime.ammo

    @property
    def facing(self) -> int:
        """The common direction used by movement, attacks, and skills."""

        return self.party.shared_facing

    @facing.setter
    def facing(self, value: int) -> None:
        self.party.set_shared_facing(value)

    @property
    def is_stealthed(self) -> bool:
        """Dash stealth: enemies cannot target or hit the player."""

        return self.action_state == 'dash'

    @property
    def is_hit_stunned(self) -> bool:
        return self.action_state == 'hit'

    @property
    def action_state(self) -> CharacterActionState:
        return self.party.active_runtime.action_state

    @property
    def attack_speed_multiplier(self) -> float:
        return self.party.active_runtime.attack_speed_multiplier

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

    def ability_id_for(self, binding: str) -> str | None:
        """Return the active character's assigned skill id for one binding."""
        field = self._ABILITY_FIELD_BY_BINDING.get(binding)
        if field is None:
            raise ValueError(f'Unknown ability binding: {binding}')
        skill_id = self._definition['abilities'].get(field)
        return str(skill_id) if skill_id is not None else None

    def handle_event(
        self,
        event: pygame.event.Event,
        app: GameApp,
    ) -> str | None:
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_LEFT:
                self._left_held = True
                return None

            if event.key == pygame.K_RIGHT:
                self._right_held = True
                return None

            if event.key == pygame.K_SPACE:
                self._jump_requested = True
                return None

            if event.key == pygame.K_a:
                self._basic_attack_held = True
                return self.try_activate_ability('basic', app)

            if event.key == pygame.K_s:
                return self.try_activate_ability('skill_s', app)

            if event.key == pygame.K_d:
                return self.try_activate_ability('skill_d', app)

            if event.key == pygame.K_x:
                return self.try_activate_ability('main_unique', app)

            if event.key == pygame.K_f:
                return self.try_activate_ability('main_ultimate', app)

            if event.key == pygame.K_w:
                return self.try_use_selected_hotbar_item(app)

            if event.key == pygame.K_q:
                return self._move_hotbar_cursor(-1)

            if event.key == pygame.K_e:
                return self._move_hotbar_cursor(1)

            if event.key == pygame.K_LSHIFT:
                return self.try_dash(app)

        elif event.type == pygame.KEYUP:
            if event.key == pygame.K_LEFT:
                self._left_held = False

            elif event.key == pygame.K_RIGHT:
                self._right_held = False

            elif event.key == pygame.K_a:
                self._basic_attack_held = False

        return None

    def try_swap_character(self, app: GameApp) -> str:
        """Swap only after the current action has actually become swappable."""

        now = app.timer.game_time
        blocked_reason = self._swap_block_reason(now)
        if blocked_reason is not None:
            return f'교체 불가: {blocked_reason}'

        active_slot = self.party.swap()
        self._apply_active_character_definition()
        self._refresh_temporary_action_state(now)
        self.velocity_y = 0.0

        # The effect runs only after the party slot was changed successfully.
        if active_slot == 'sub':
            app.audio.play_effect('switch_to_sub')
            return f'{self.display_name} (서브)로 교체'

        app.audio.play_effect('switch_to_main')
        return f'{self.display_name} (메인)으로 교체'

    def try_activate_ability(
        self,
        binding: str,
        app: GameApp,
        *,
        quiet_when_blocked: bool = False,
    ) -> str | None:
        """Activate one input binding and queue its gameplay result on success."""

        if binding not in self._ABILITY_FIELD_BY_BINDING:
            raise ValueError(f'Unknown ability binding: {binding}')

        if (
            binding in ('main_unique', 'main_ultimate')
            and self.party.active_slot != 'main'
        ):
            return None if quiet_when_blocked else '메인 캐릭터 전용 스킬입니다.'

        abilities = self._definition['abilities']
        skill_id = abilities.get(self._ABILITY_FIELD_BY_BINDING[binding])

        if skill_id is None:
            labels = {
                'skill_s': 'S 스킬',
                'skill_d': 'D 스킬',
                'main_unique': 'X 고유 스킬',
                'main_ultimate': 'F 궁극기',
            }
            return None if quiet_when_blocked else (
                f"{labels.get(binding, '기본 공격')}이(가) 아직 배정되지 않았습니다."
            )

        return self._try_activate_skill(
            str(skill_id),
            app,
            is_basic_attack=(binding == 'basic'),
            quiet_when_blocked=quiet_when_blocked,
        )

    def try_dash(self, app: GameApp) -> str | None:
        """Start the party-shared dash and cancel eligible current actions.

        Dash is a defensive cancel. It may replace idle, walking, jump, fall,
        attack, skill, or hit-stun. It never replaces death, respawn wait, or
        another dash. Skill cooldowns are already started when the skill begins,
        therefore canceling a skill keeps its cooldown running immediately.
        """

        now = app.timer.game_time
        self._refresh_temporary_action_state(now)

        runtime = self.party.active_runtime

        if self.party.shared_hp <= 0 or runtime.action_state == 'dead':
            return '사망 상태에서는 대시할 수 없습니다.'

        if self.party.is_respawning or runtime.action_state == 'respawn_wait':
            return '리스폰 대기 상태에서는 대시할 수 없습니다.'

        if runtime.action_state == 'dash':
            return '이미 대시 중입니다.'

        if runtime.action_state not in self._DASH_CANCEL_ALLOWED_STATES:
            return '현재 상태에서는 대시할 수 없습니다.'

        movement = self.party.shared_settings['movement']
        ready_at = self.party.shared_dash_ready_at
        if now < ready_at:
            return f'대시 재사용 대기: {ready_at - now:.1f}초'

        direction = int(self._right_held) - int(self._left_held)
        if direction == 0:
            direction = self.facing
        else:
            # Movement direction, attack direction, and skill direction are one
            # shared party direction.
            self.facing = direction

        duration = float(movement['dash_duration_seconds'])
        cooldown = float(movement['dash_cooldown_seconds'])

        runtime.dash_direction = 1 if direction >= 0 else -1
        runtime.dash_active_until = now + duration
        self.party.shared_dash_ready_at = now + cooldown

        # Cancel any current attack / skill / hit lock. The attack or skill's
        # cooldown is deliberately not refunded.
        runtime.action_state = 'dash'
        runtime.action_locked_until = runtime.dash_active_until

        # Jump, fall, and dash do not use separate image files. They display
        # the active character's Walk_## (1).png without advancing frames.
        runtime.animation_name = 'walk'
        runtime.animation_elapsed = 0.0
        runtime.animation_playback_speed = 1.0

        return '대시'

    def try_use_selected_hotbar_item(self, app: GameApp) -> str | None:
        """Use the currently selected shared item with W.

        Inventory and normal-item cooldowns are party-wide.
        """

        now = app.timer.game_time
        self._refresh_temporary_action_state(now)

        if self.action_state not in self._ACTION_ALLOWED_STATES:
            return '현재 행동 중에는 아이템을 사용할 수 없습니다.'

        item_id = self.party.selected_hotbar_item_id
        if item_id is None:
            return '사용할 아이템이 없습니다.'

        item = app.data.record('items', item_id)
        if str(item['item_type']) != 'consumable':
            return f"{item['display_name']}은(는) 사용할 수 없는 아이템입니다."

        ready_at = self.party.shared_item_cooldown_ready_at.get(item_id, 0.0)
        if now < ready_at:
            return (
                f"{item['display_name']} 재사용 대기: "
                f'{ready_at - now:.1f}초'
            )

        effect = item['effect']
        effect_type = str(effect.get('effect_type', ''))

        if effect_type == 'heal':
            if self.hp >= self.max_hp:
                return 'HP가 이미 가득 찼습니다.'

            amount = int(effect['amount'])
            if not self.party.consume_shared_item(item_id):
                return '아이템이 없습니다.'

            hp = self.party.heal(amount)
            self.party.shared_item_cooldown_ready_at[item_id] = (
                now + float(item.get('use_cooldown_seconds', 0.0))
            )
            return f"{item['display_name']} 사용 · 공유 HP {hp}/{self.max_hp}"

        return f"{item['display_name']}은(는) 아직 사용할 수 없습니다."

    def _move_hotbar_cursor(self, direction: int) -> str:
        item_id = self.party.move_hotbar_cursor(direction)
        if item_id is None:
            return '핫바에 아이템이 없습니다.'

        amount = self.party.shared_inventory.get(item_id, 0)
        return f'핫바 선택: {item_id} x{amount}'

    def _try_activate_skill(
        self,
        skill_id: str,
        app: GameApp,
        *,
        is_basic_attack: bool,
        quiet_when_blocked: bool,
    ) -> str | None:
        now = app.timer.game_time
        self._refresh_temporary_action_state(now)

        runtime = self.party.active_runtime
        if runtime.action_state not in self._ACTION_ALLOWED_STATES:
            return None if quiet_when_blocked else (
                '현재 행동 중에는 스킬을 사용할 수 없습니다.'
            )

        skill = app.data.record('skills', skill_id)
        cooldown_seconds = float(skill['cooldown_seconds'])
        action_duration = float(skill['action_duration_seconds'])

        if is_basic_attack:
            # Attack interval means:
            # bullet fired now -> next bullet may fire after this exact interval.
            # A higher multiplier shortens both the firing interval and motion.
            multiplier = max(0.01, runtime.attack_speed_multiplier)
            cooldown_seconds = (
                float(skill.get('attack_interval_seconds', cooldown_seconds))
                / multiplier
            )
            action_duration = action_duration / multiplier

        ready_at = runtime.cooldown_ready_at.get(skill_id, 0.0)
        if now < ready_at:
            if quiet_when_blocked:
                return None
            return (
                f"{skill['display_name']} 재사용 대기: "
                f'{ready_at - now:.1f}초'
            )

        resource_cost = skill.get('resource_cost')
        if resource_cost:
            ammo_type = str(resource_cost['ammo_type'])
            amount = int(resource_cost['amount'])
            current_ammo = runtime.ammo.get(ammo_type, 0)

            if current_ammo < amount:
                if quiet_when_blocked:
                    return None
                return (
                    f"{skill['display_name']} 탄약 부족: "
                    f'{ammo_type} {current_ammo}/{amount}'
                )

            runtime.ammo[ammo_type] = current_ammo - amount

        runtime.cooldown_ready_at[skill_id] = now + cooldown_seconds

        action_duration = min(action_duration, cooldown_seconds)
        animation_name = str(
            skill.get(
                'animation_name',
                'attack'
                if str(skill['action_state']) == 'attack'
                else 'skill',
            )
        )

        self.begin_action(
            str(skill['action_state']),
            action_duration,
            now,
            app,
            animation_name=animation_name,
        )

        self._pending_skill_ids.append(skill_id)
        return f"{skill['display_name']} 사용"

    def begin_action(
        self,
        action_state: str,
        duration_seconds: float,
        now: float,
        app: GameApp,
        *,
        animation_name: str,
    ) -> None:
        """Start a swap-blocking action and fit its animation to that duration."""

        if action_state not in ('attack', 'skill'):
            raise ValueError(
                'action_state must be "attack" or "skill".'
            )

        runtime = self.party.active_runtime
        duration_seconds = max(0.0, duration_seconds)

        # Frame count is read from the actual files. The visible action is
        # compressed/expanded so its final frame arrives when the action lock
        # expires. A faster attack speed therefore makes the motion faster too.
        natural_duration = CharacterSpriteCache.get_animation_duration(
            app,
            self._definition,
            animation_name,
        )

        playback_speed = 1.0
        if natural_duration is not None and duration_seconds > 0.0:
            playback_speed = natural_duration / duration_seconds

        runtime.action_state = action_state
        runtime.action_locked_until = now + duration_seconds
        runtime.animation_name = animation_name
        runtime.animation_elapsed = 0.0
        runtime.animation_playback_speed = max(0.01, playback_speed)

    def consume_pending_skill_ids(self) -> tuple[str, ...]:
        """Return successful actions awaiting PlayScene world spawning."""

        pending = tuple(self._pending_skill_ids)
        self._pending_skill_ids.clear()
        return pending

    def take_damage(self, amount: int, app: GameApp) -> bool:
        """Apply contact/projectile damage unless dash-stealthed or invulnerable.

        A normal hit starts a 0.5-second hit-stun / invulnerability period.
        Dash is not normal invulnerability: it is stealth and the collision
        handler skips the player completely while dashing.
        """

        now = app.timer.game_time
        runtime = self.party.active_runtime

        if self.party.shared_hp <= 0 or self.party.is_respawning:
            return False

        if self.is_stealthed:
            return False

        if now < runtime.hit_invulnerable_until:
            return False

        damage = max(0, int(amount))
        if damage <= 0:
            return False

        self.party.apply_damage(damage)

        invulnerability_seconds = max(
            0.0,
            float(
                self.party.shared_settings['combat'][
                    'contact_invulnerability_seconds'
                ]
            ),
        )
        until = now + invulnerability_seconds

        runtime.hit_invulnerable_until = until
        runtime.action_locked_until = until

        if self.party.shared_hp <= 0:
            # The next update converts this one-frame death state into the
            # shared respawn wait. Dash and swapping are blocked immediately.
            runtime.action_state = 'dead'
            runtime.action_locked_until = float('inf')
            runtime.animation_name = 'hit'
            runtime.animation_elapsed = 0.0
            runtime.animation_playback_speed = 1.0
        else:
            runtime.action_state = 'hit'
            runtime.animation_name = 'hit'
            runtime.animation_elapsed = 0.0
            runtime.animation_playback_speed = 1.0

        return True

    def enter_respawn_wait(self, app: GameApp) -> None:
        """Start the five-second party-wide wait after death."""

        if self.party.is_respawning:
            return

        self.party.start_shared_respawn_wait(app.timer.game_time)

    def finish_respawn(self) -> None:
        """Restore party HP and return the active player to initial spawn."""

        self.party.finish_shared_respawn()
        self._apply_active_character_definition()

        self.x = self._respawn_x
        self.y = self._respawn_y
        self.velocity_y = 0.0
        self.is_grounded = False
        self._jump_requested = False

    def _update_respawn_state(self, now: float, app: GameApp) -> bool:
        """Advance death -> respawn wait -> initial spawn.

        Returns True while world movement must remain paused.
        """

        runtime = self.party.active_runtime

        if runtime.action_state == 'dead':
            self.enter_respawn_wait(app)
            return True

        if runtime.action_state != 'respawn_wait':
            return False

        if now < self.party.shared_respawn_ready_at:
            return True

        self.finish_respawn()
        return False

    def add_item(
        self,
        item_id: str,
        amount: int,
        item_definition: dict[str, Any],
    ) -> str:
        """Add pickups under the project's sharing rules."""

        effect = item_definition.get('effect', {})
        if effect.get('effect_type') == 'add_ammo':
            ammo_type = str(effect['ammo_type'])
            added = int(effect['amount']) * max(0, int(amount))
            self.ammo[ammo_type] = self.ammo.get(ammo_type, 0) + added
            return (
                f"{item_definition['display_name']} "
                f'+{added} ({ammo_type}, {self.display_name})'
            )

        accepted = self.party.add_shared_item(
            item_id,
            amount,
            item_definition,
        )

        if accepted == 0:
            return f"{item_definition['display_name']}은(는) 더 들 수 없습니다."

        return f"{item_definition['display_name']} +{accepted} (공용)"

    def add_experience(self, amount: int) -> int:
        return self.party.add_experience(amount)

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

        direction = int(self._right_held) - int(self._left_held)
        now = app.timer.game_time

        if self._update_respawn_state(now, app):
            self._jump_requested = False
            self._update_animation(delta_seconds, direction)
            return

        self._refresh_temporary_action_state(now)

        # Holding A repeatedly fires only as soon as the basic attack interval
        # allows it. One key press still fires instantly through handle_event().
        if self._basic_attack_held:
            self.try_activate_ability(
                'basic',
                app,
                quiet_when_blocked=True,
            )

        # Hit-stun blocks every directional movement input (including future
        # up/down movement systems) and blocks jumping. Held left/right values
        # are kept so movement resumes naturally when the stun ends.
        movement_inputs_locked = self.is_hit_stunned

        if self.action_state == 'dash':
            dash_speed = (
                self.move_speed
                * float(
                    self.party.shared_settings['movement'][
                        'dash_speed_multiplier'
                    ]
                )
            )
            self._move_horizontally(
                self.party.active_runtime.dash_direction
                * dash_speed
                * delta_seconds,
                terrain,
            )
        elif not movement_inputs_locked and direction != 0:
            self.facing = direction
            self._move_horizontally(
                direction * self.move_speed * delta_seconds,
                terrain,
            )

        if (
            self._jump_requested
            and self.is_grounded
            and not movement_inputs_locked
            and self.action_state in self._ACTION_ALLOWED_STATES
        ):
            self.velocity_y = self.jump_speed
            self.is_grounded = False
            self._set_airborne_state('jump')

        self._move_vertically(delta_seconds, terrain)
        self._clamp_to_world_bounds(world)

        self._jump_requested = False
        self._update_animation(delta_seconds, direction)

    def _apply_active_character_definition(self) -> None:
        self._definition = self.party.active_definition
        collider = self.party.shared_settings['collider']
        self.width = float(collider['width'])
        self.height = float(collider['height'])

        stats = self._definition['stats']
        movement = self.party.shared_settings['movement']

        self.move_speed = float(stats['move_speed'])
        self.gravity = float(movement['gravity'])
        self.jump_speed = float(movement['jump_speed'])
        self.max_fall_speed = float(movement['max_fall_speed'])

    def _swap_block_reason(self, now: float) -> str | None:
        self._refresh_temporary_action_state(now)
        runtime = self.party.active_runtime

        if self.party.shared_hp <= 0 or runtime.action_state == 'dead':
            return '사망 상태입니다.'

        if runtime.action_state == 'respawn_wait':
            return '리스폰 대기 상태입니다.'

        if now < runtime.hit_invulnerable_until:
            remaining = runtime.hit_invulnerable_until - now
            return f'피격 무적 상태입니다. ({remaining:.1f}초)'

        labels = {
            'attack': '공격 중입니다.',
            'skill': '스킬 사용 중입니다.',
            'dash': '대시 중입니다.',
            'jump': '점프 중입니다.',
            'fall': '추락 중입니다.',
            'hit': '피격 상태입니다.',
        }
        if runtime.action_state in labels:
            return labels[runtime.action_state]

        if runtime.action_state not in self._SWAP_ALLOWED_STATES:
            return '현재 상태에서는 교체할 수 없습니다.'

        return None

    def _refresh_temporary_action_state(self, now: float) -> None:
        runtime = self.party.active_runtime

        if runtime.action_state not in ('attack', 'skill', 'hit', 'dash'):
            return

        if now < runtime.action_locked_until:
            return

        # When a timed action finishes in the air, do not incorrectly return
        # to idle/walk. The player remains in jump or fall until terrain
        # collision says that they have landed.
        if not self.is_grounded:
            state = 'jump' if self.velocity_y > 0.0 else 'fall'
            self._set_airborne_state(state)
            return

        self._set_grounded_state()

    def _update_animation(
        self,
        delta_seconds: float,
        direction: int,
    ) -> None:
        runtime = self.party.active_runtime

        if runtime.action_state in ('idle', 'walk'):
            next_name = 'walk' if direction != 0 else 'idle'
            runtime.action_state = next_name

            if runtime.animation_name != next_name:
                runtime.animation_name = next_name
                runtime.animation_elapsed = 0.0
                runtime.animation_playback_speed = 1.0
            else:
                runtime.animation_elapsed += delta_seconds
            return

        if runtime.action_state in ('jump', 'fall', 'dash'):
            # All three states intentionally hold Walk_## (1).png:
            # elapsed must not advance while airborne or dashing.
            runtime.animation_name = 'walk'
            runtime.animation_elapsed = 0.0
            runtime.animation_playback_speed = 1.0
            return

        # attack / skill / hit keeps its own animation until the action lock ends.
        runtime.animation_elapsed += delta_seconds

    def _set_airborne_state(self, state: str) -> None:
        """Enter jump/fall and hold Walk_## (1).png on screen."""

        if state not in ('jump', 'fall'):
            raise ValueError('Airborne state must be "jump" or "fall".')

        runtime = self.party.active_runtime
        runtime.action_state = state
        runtime.animation_name = 'walk'
        runtime.animation_elapsed = 0.0
        runtime.animation_playback_speed = 1.0

    def _set_grounded_state(self) -> None:
        """Return to natural idle/walk without restarting it every frame.

        Terrain contact is checked every update, so resetting
        ``animation_elapsed`` here unconditionally would pin Idle and Walk to
        frame (1). The timer is reset only when the visible state actually
        changes, such as landing after jump/fall or releasing a movement key.
        """

        runtime = self.party.active_runtime
        direction = int(self._right_held) - int(self._left_held)
        state = 'walk' if direction != 0 else 'idle'

        already_in_same_animation = (
            runtime.action_state == state
            and runtime.animation_name == state
        )

        runtime.action_state = state
        runtime.animation_name = state

        if already_in_same_animation:
            return

        runtime.animation_elapsed = 0.0
        runtime.animation_playback_speed = 1.0

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
            if not block.is_solid or not self._vertical_overlaps(block):
                continue

            if movement_x > 0.0:
                crossed_left_side = (
                    previous_right <= block.left + self._COLLISION_EPSILON
                    and self.right > block.left
                )
                if crossed_left_side:
                    self.x = block.left - self.width * 0.5

            else:
                crossed_right_side = (
                    previous_left >= block.right - self._COLLISION_EPSILON
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

        self.velocity_y = max(
            self.velocity_y - self.gravity * delta_seconds,
            -self.max_fall_speed,
        )
        self.y += self.velocity_y * delta_seconds
        self.is_grounded = False

        if self.velocity_y <= 0.0:
            self._resolve_landing(previous_bottom, terrain)

            # The moment +Y speed reaches zero or becomes negative, the state
            # becomes fall. It remains fall until _resolve_landing() detects a
            # real terrain collision and sets is_grounded.
            if self.is_grounded:
                # A ground contact happens every physics frame while standing.
                # Only jump/fall are released by landing. Attack, skill, hit,
                # and dash keep their own action locks until their timers end.
                if self.action_state in ('idle', 'walk', 'jump', 'fall'):
                    self._set_grounded_state()
            elif self.action_state in ('idle', 'walk', 'jump', 'fall'):
                self._set_airborne_state('fall')
            return

        self._resolve_ceiling(previous_top, terrain)

        # A ceiling impact can set velocity_y to zero. In that case the player
        # begins falling immediately and still stays in fall until landing.
        if self.velocity_y <= 0.0:
            if self.action_state in ('idle', 'walk', 'jump', 'fall'):
                self._set_airborne_state('fall')
        elif self.action_state in ('idle', 'walk', 'jump', 'fall'):
            self._set_airborne_state('jump')

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
                previous_bottom >= block.top - self._COLLISION_EPSILON
                and self.bottom <= block.top
            )
            if not crossed_top:
                continue

            if landing_block is None or block.top > landing_block.top:
                landing_block = block

        if landing_block is not None:
            self.y = landing_block.top + self.height * 0.5
            self.velocity_y = 0.0
            self.is_grounded = True

    def _resolve_ceiling(
        self,
        previous_top: float,
        terrain: tuple[TerrainBlock, ...],
    ) -> None:
        ceiling_block: TerrainBlock | None = None

        for block in terrain:
            if not block.is_solid or not self._horizontal_overlaps(block):
                continue

            crossed_bottom = (
                previous_top <= block.bottom + self._COLLISION_EPSILON
                and self.top >= block.bottom
            )
            if not crossed_bottom:
                continue

            if ceiling_block is None or block.bottom < ceiling_block.bottom:
                ceiling_block = block

        if ceiling_block is not None:
            self.y = ceiling_block.bottom - self.height * 0.5
            self.velocity_y = 0.0

    def _vertical_overlaps(self, block: TerrainBlock) -> bool:
        return self.top > block.bottom and self.bottom < block.top

    def _horizontal_overlaps(self, block: TerrainBlock) -> bool:
        return self.right > block.left and self.left < block.right

    def _clamp_to_world_bounds(self, world: World) -> None:
        bounds = world.bounds
        half_width = self.width * 0.5
        half_height = self.height * 0.5

        if self.left < bounds.left:
            self.x = bounds.left + half_width
        elif self.right > bounds.right:
            self.x = bounds.right - half_width

        if self.bottom < bounds.bottom:
            self.y = bounds.bottom + half_height
            self.velocity_y = max(0.0, self.velocity_y)
            self.is_grounded = True

            if self.action_state in ('jump', 'fall'):
                self._set_grounded_state()

        if self.top > bounds.top:
            self.y = bounds.top - half_height
            self.velocity_y = min(0.0, self.velocity_y)

    def draw(
        self,
        screen: pygame.Surface,
        world: World,
        app: GameApp,
        camera: Camera,
    ) -> None:
        visual = self._definition['visual']
        draw_width = float(visual['draw_width'])
        draw_height = float(visual['draw_height'])

        runtime = self.party.active_runtime
        resolved_animation_name = CharacterSpriteCache.resolve_animation_name(
            app,
            self._definition,
            runtime.animation_name,
        )

        # The large image is bottom-anchored to the 34 x 68 collider. JSON
        # offsets move the picture only; the actual collision box stays put.
        offset_x, offset_y = CharacterSpriteCache.get_draw_offset(
            self._definition,
            resolved_animation_name,
            self.facing,
        )
        visual_center_x = self.x + offset_x
        visual_center_y = (
            self.bottom
            + draw_height * 0.5
            + offset_y
        )

        if not camera.is_world_rect_visible(
            visual_center_x,
            visual_center_y,
            draw_width,
            draw_height,
        ):
            return

        image = CharacterSpriteCache.get_frame(
            app,
            self._definition,
            resolved_animation_name,
            runtime.animation_elapsed,
            self.facing,
            playback_speed=runtime.animation_playback_speed,
            loop=runtime.action_state in ('idle', 'walk', 'dash'),
        )
        rect = camera.rect_from_world_center(
            visual_center_x,
            visual_center_y,
            draw_width,
            draw_height,
        )
        screen.blit(image, rect.topleft)
