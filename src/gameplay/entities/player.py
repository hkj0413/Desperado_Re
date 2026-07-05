from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pygame

from src.gameplay.character_assets import CharacterSpriteCache
from src.gameplay.entities.base import Entity
from src.gameplay.entities.terrain import TerrainBlock
from src.gameplay.party import CharacterActionState, PartyManager, ReloadRuntime

if TYPE_CHECKING:
    from src.app import GameApp
    from src.core.camera import Camera
    from src.core.world import World


class Player(Entity):
    updates_each_frame = True
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
    # New actions/items normally begin only from a calm grounded state.
    # Standard SG reload is the explicit exception and checks locomotion_state
    # independently below, matching the old Jump/Fall + Reload_SG behavior.
    _ACTION_ALLOWED_STATES = frozenset(('idle', 'walk'))
    _SWAP_ALLOWED_STATES = frozenset(('idle', 'walk'))
    _DASH_CANCEL_ALLOWED_STATES = frozenset(
        ('idle', 'walk', 'jump', 'fall', 'attack', 'skill', 'reload', 'hit')
    )
    _ABILITY_FIELD_BY_BINDING = {
        'basic': 'basic_attack_id',
        'skill_s': 'skill_s_id',
        'skill_d': 'skill_d_id',
        'main_unique': 'main_unique_skill_id',
        'main_ultimate': 'main_ultimate_skill_id',
    }
    # Mirrors the original Desperado character-state classification while
    # keeping it independent from movement and reload state.
    _COMBAT_STATE_BY_BINDING = {
        'basic': 0,
        'main_unique': 1,
        'skill_s': 2,
        'skill_d': 3,
        'main_ultimate': 4,
    }
    _STANDARD_RELOAD_ALLOWED_LOCOMOTION_STATES = frozenset(
        ('idle', 'walk', 'jump', 'fall', 'dash')
    )
    _RECOIL_RELOAD_ALLOWED_LOCOMOTION_STATES = frozenset(('idle', 'walk'))

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
        self._down_held = False
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
        # Reload effects may use a direction captured at reload start, not the
        # possibly changed shared facing at release time.
        self._pending_projectile_requests: list[tuple[str, int]] = []
        # Last accepted hit is consumed only by PlayScene feedback text. It does
        # not control gameplay; state remains the source of truth.
        self.last_damage_outcome = 'none'

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
    def is_dodging(self) -> bool:
        """Dash is the true dodge state: collision does not become a hit."""

        return self.action_state == 'dash'

    @property
    def has_stagger_immunity(self) -> bool:
        """Whether the currently running action absorbs hit-stun only.

        It does *not* negate HP damage. A successful hit still starts the
        common post-hit invulnerability window.
        """

        runtime = self.party.active_runtime
        return bool(runtime.active_action_stagger_immune)

    @property
    def action_state(self) -> CharacterActionState:
        return self.party.active_runtime.action_state

    @property
    def locomotion_state(self) -> str:
        """Physical state: idle/walk/jump/fall/dash, independent of actions."""

        return self.party.active_runtime.locomotion_state

    @property
    def combat_state(self) -> int:
        """0 basic/default, 1 unique, 2 S, 3 D, 4 ultimate."""

        return self.party.active_runtime.combat_state

    @property
    def display_state(self) -> CharacterActionState:
        """State intended for HUD text when an overlay action is active."""

        runtime = self.party.active_runtime
        if runtime.reload is not None:
            return 'reload'
        return runtime.action_state

    @property
    def attack_speed_multiplier(self) -> float:
        return self.party.active_runtime.attack_speed_multiplier

    @property
    def is_standard_reload_active(self) -> bool:
        """True while an SG-style reload owns its own timer and art."""

        reload_state = self.party.active_runtime.reload
        return reload_state is not None and reload_state.mode == 'standard'

    def _active_standard_reload(self) -> ReloadRuntime | None:
        reload_state = self.party.active_runtime.reload
        if reload_state is not None and reload_state.mode == 'standard':
            return reload_state
        return None

    @property
    def is_visual_hidden(self) -> bool:
        """Hide sprite and debug bounds only during respawn wait.

        The Die animation remains visible while the action state is ``dead``.
        ``PartyManager`` switches all member states to ``respawn_wait`` only
        after that non-looping animation has completed.
        """

        return self.party.is_respawning or self.action_state == 'respawn_wait'

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
        """Handle only gameplay controls.

        ← / →      : horizontal movement
        Left Shift : dash
        Space      : jump
        ↑          : unassigned
        ↓          : held modifier for the R93 stationary reload
        A     : basic attack
        S / D : skills
        X     : main-only unique skill
        C     : main-only ultimate
        R     : reload
        """

        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_LEFT:
                self._left_held = True
                return None

            if event.key == pygame.K_RIGHT:
                self._right_held = True
                return None

            if event.key == pygame.K_DOWN:
                self._down_held = True
                return None

            # Up is intentionally left unassigned for a future feature.
            if event.key == pygame.K_SPACE:
                self._jump_requested = True
                return None

            if event.key == pygame.K_LSHIFT:
                return self.try_dash(app)

            if event.key == pygame.K_a:
                self._basic_attack_held = True
                return self.try_activate_ability('basic', app)

            if event.key == pygame.K_s:
                return self.try_activate_ability('skill_s', app)

            if event.key == pygame.K_d:
                return self.try_activate_ability('skill_d', app)

            if event.key == pygame.K_x:
                return self.try_activate_ability('main_unique', app)

            if event.key == pygame.K_c:
                return self.try_activate_ability('main_ultimate', app)

            if event.key == pygame.K_r:
                return self.try_reload(app)

            if event.key == pygame.K_w:
                return self.try_use_selected_hotbar_item(app)

            if event.key == pygame.K_q:
                return self._move_hotbar_cursor(-1)

            if event.key == pygame.K_e:
                return self._move_hotbar_cursor(1)

        elif event.type == pygame.KEYUP:
            if event.key == pygame.K_LEFT:
                self._left_held = False

            elif event.key == pygame.K_RIGHT:
                self._right_held = False

            elif event.key == pygame.K_DOWN:
                self._down_held = False

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
                'main_ultimate': 'C 궁극기',
            }
            return None if quiet_when_blocked else (
                f"{labels.get(binding, '기본 공격')}이(가) 아직 배정되지 않았습니다."
            )

        return self._try_activate_skill(
            str(skill_id),
            app,
            binding=binding,
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

        # Dash cancels an ordinary attack/skill/recoil-reload exactly like the
        # old state machine left its current skill state. A standard SG reload
        # is the deliberate exception: its independent reload action continues
        # through dash, jump, fall, and walking.
        keep_standard_reload = self.is_standard_reload_active
        if not keep_standard_reload:
            self._cancel_active_action()

        runtime.locomotion_state = 'dash'
        runtime.action_state = 'dash'
        runtime.action_locked_until = runtime.dash_active_until

        if not keep_standard_reload:
            # Jump, fall, and dash do not use separate image files. They display
            # the active character's Walk_## (1).png without advancing frames.
            runtime.animation_name = 'walk'
            runtime.animation_elapsed = 0.0
            runtime.animation_playback_speed = 1.0

        return '대시'

    def try_reload(self, app: GameApp) -> str:
        """Reload the active character's personal magazine with R.

        HKCAWS uses a normal locked Reload_SG animation. R93 uses the old
        recoil-reload rule: after a short release delay it fires a reload
        projectile and makes a small jump. Holding ↓ when R is pressed keeps
        the jump in place; otherwise the character also recoils backward.
        """

        now = app.timer.game_time
        self._refresh_temporary_action_state(now)
        runtime = self.party.active_runtime

        if self.party.shared_hp <= 0 or runtime.action_state == 'dead':
            return '사망 상태에서는 장전할 수 없습니다.'

        if self.party.is_respawning or runtime.action_state == 'respawn_wait':
            return '리스폰 대기 상태에서는 장전할 수 없습니다.'

        if runtime.reload is not None:
            return '이미 장전 중입니다.'

        reload_definition = self._definition['reload']
        mode = str(reload_definition['mode'])

        # Reload is its own action layer.  Unlike the old combined action_state
        # gate, an SG standard reload may begin while the physical state is
        # jump, fall, walk, or dash.  It cannot begin over an active attack,
        # skill, or hit-stun; those are distinct foreground actions.
        if runtime.active_action_id is not None or runtime.action_state == 'hit':
            return '현재 행동 중에는 장전할 수 없습니다.'

        allowed_locomotion_states = (
            self._STANDARD_RELOAD_ALLOWED_LOCOMOTION_STATES
            if mode == 'standard'
            else self._RECOIL_RELOAD_ALLOWED_LOCOMOTION_STATES
        )
        if runtime.locomotion_state not in allowed_locomotion_states:
            return '현재 이동 상태에서는 장전할 수 없습니다.'

        if bool(reload_definition.get('requires_empty_magazine', False)):
            if any(
                runtime.ammo.get(ammo_type, 0) > 0
                for ammo_type in runtime.max_ammo
            ):
                return '이 캐릭터는 탄창이 비었을 때만 장전할 수 있습니다.'

        if not any(
            runtime.ammo.get(ammo_type, 0) < maximum
            for ammo_type, maximum in runtime.max_ammo.items()
        ):
            return '탄약이 이미 가득 찼습니다.'

        duration = float(reload_definition['action_duration_seconds'])
        animation_name = str(reload_definition['animation_name'])

        direction = self.facing
        release_at: float | None = None
        projectile_skill_id: str | None = None
        recoil_speed = 0.0
        jump_speed = 0.0

        if mode == 'recoil_projectile':
            release_at = now + float(
                reload_definition['release_delay_seconds']
            )
            projectile_skill_id = str(
                reload_definition['projectile_skill_id']
            )
            jump_speed = self.jump_speed * float(
                reload_definition['jump_speed_multiplier']
            )

            # ↓ is sampled at the moment R is pressed. Releasing ↓ afterward
            # does not turn a stationary reload into a backward recoil.
            if not self._down_held:
                recoil_speed = self.move_speed * float(
                    reload_definition['recoil_speed_multiplier']
                )

        # An SG standard reload empties its magazine immediately. The reload
        # cannot visually be in progress while leftover shells are still usable.
        # Ammunition is restored only when complete_at is reached.
        if mode == 'standard':
            for ammo_type in runtime.max_ammo:
                runtime.ammo[ammo_type] = 0

        natural_duration = CharacterSpriteCache.get_animation_duration(
            app,
            self._definition,
            animation_name,
        )
        playback_speed = 1.0
        if natural_duration is not None and duration > 0.0:
            playback_speed = natural_duration / duration

        runtime.reload = ReloadRuntime(
            mode=mode,
            direction=direction,
            release_at=release_at,
            projectile_skill_id=projectile_skill_id,
            recoil_speed=recoil_speed,
            jump_speed=jump_speed,
            complete_at=now + duration,
            animation_name=animation_name,
            animation_playback_speed=max(0.01, playback_speed),
        )

        self.begin_action(
            'reload',
            duration,
            now,
            app,
            animation_name=animation_name,
            action_id=f'reload:{self.character_id}',
            stagger_immune=bool(
                reload_definition.get('stagger_immunity', True)
            ),
            # The reload sheet is an overlay. Standard SG reload deliberately
            # leaves the physical jump/fall/walk/dash state untouched.
            preserve_locomotion=(mode == 'standard'),
            combat_state=0,
        )

        if mode == 'recoil_projectile':
            return (
                '반동 장전 준비 · ↓를 누른 채 시작하면 제자리 점프'
                if self._down_held
                else '반동 장전 준비'
            )

        return '장전'

    def _advance_reload(self, now: float) -> None:
        """Advance reload timers independently from action_state.

        SG standard reloads remain active even when their physical state turns
        into jump, fall, dash, or hit. R93 keeps its delayed projectile release
        but uses the same independent completion time.
        """

        runtime = self.party.active_runtime
        reload_state = runtime.reload
        if reload_state is None:
            return

        if (
            reload_state.mode == 'recoil_projectile'
            and not reload_state.released
            and reload_state.release_at is not None
            and now >= reload_state.release_at
        ):
            reload_state.released = True

            if reload_state.projectile_skill_id is not None:
                self._pending_projectile_requests.append(
                    (
                        reload_state.projectile_skill_id,
                        reload_state.direction,
                    )
                )

            # The old R93 reload performs a small upward kick in both variants.
            # Only the non-↓ variant also receives horizontal backward recoil.
            if reload_state.jump_speed > 0.0:
                self.velocity_y = max(self.velocity_y, reload_state.jump_speed)
                self.is_grounded = False

        if now >= reload_state.complete_at:
            self._finish_reload()

    def _finish_reload(self) -> None:
        """Complete one still-active reload by restoring its magazine.

        A cancelled reload has ``runtime.reload is None``. It must never refill
        ammo merely because an old visible ``reload`` state reaches its former
        timer, especially after death or a dash cancellation.
        """

        runtime = self.party.active_runtime
        if runtime.reload is None:
            return

        for ammo_type, maximum in runtime.max_ammo.items():
            runtime.ammo[ammo_type] = maximum
        runtime.reload = None
        if runtime.active_action_id == f'reload:{self.character_id}':
            self._clear_active_action_metadata()

    def try_use_selected_hotbar_item(self, app: GameApp) -> str | None:
        """Use the currently selected shared item with W.

        Inventory and normal-item cooldowns are party-wide.
        """

        now = app.timer.game_time
        self._advance_reload(now)
        self._refresh_temporary_action_state(now)

        if self.is_standard_reload_active:
            return '장전 중에는 아이템을 사용할 수 없습니다.'

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

    def _can_start_ability_from_current_state(
        self,
        is_basic_attack: bool,
    ) -> bool:
        """Return whether the active state allows this input to begin.

        The old Desperado state machine let SG's basic attack visually override
        jump/fall/hit/dash. Re: keeps that rule data-driven: HKCAWS lists every
        locomotion/reaction state from which its basic attack can begin, while
        R93 and all skills retain the normal grounded idle/walk gate.
        """

        runtime = self.party.active_runtime
        if is_basic_attack:
            configured_states = self._definition.get(
                'combat_rules', {}
            ).get('basic_attack_allowed_states')
            if isinstance(configured_states, list):
                return runtime.action_state in configured_states

        return runtime.action_state in self._ACTION_ALLOWED_STATES

    def _try_activate_skill(
        self,
        skill_id: str,
        app: GameApp,
        *,
        binding: str,
        is_basic_attack: bool,
        quiet_when_blocked: bool,
    ) -> str | None:
        now = app.timer.game_time
        self._advance_reload(now)
        self._refresh_temporary_action_state(now)

        runtime = self.party.active_runtime

        if self.is_standard_reload_active:
            return None if quiet_when_blocked else '장전 중에는 스킬을 사용할 수 없습니다.'

        if not self._can_start_ability_from_current_state(is_basic_attack):
            return None if quiet_when_blocked else (
                '현재 행동 중에는 스킬을 사용할 수 없습니다.'
            )

        skill = app.data.record('skills', skill_id)

        # R93-style characters may require every attack-type action to begin
        # from a fully idle grounded state. Future skills with action_state
        # "attack" inherit the same rule without a character-id branch.
        if (
            bool(
                self._definition.get('combat_rules', {}).get(
                    'attack_requires_idle_grounded',
                    False,
                )
            )
            and str(skill['action_state']) == 'attack'
            and (
                runtime.action_state != 'idle'
                or not self.is_grounded
                or self._left_held
                or self._right_held
            )
        ):
            return None if quiet_when_blocked else (
                '이 캐릭터는 대기 상태에서만 공격할 수 있습니다.'
            )

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

        default_stagger_immunity = binding in set(
            self._definition.get('combat_rules', {}).get(
                'stagger_immune_bindings',
                (),
            )
        )
        stagger_immune = bool(
            skill.get('stagger_immunity', default_stagger_immunity)
        )

        self.begin_action(
            str(skill['action_state']),
            action_duration,
            now,
            app,
            animation_name=animation_name,
            action_id=skill_id,
            stagger_immune=stagger_immune,
            combat_state=self._COMBAT_STATE_BY_BINDING[binding],
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
        action_id: str | None = None,
        stagger_immune: bool = False,
        preserve_locomotion: bool = False,
        combat_state: int = 0,
    ) -> None:
        """Start a swap-blocking action and fit its animation to that duration."""

        if action_state not in ('attack', 'skill', 'reload'):
            raise ValueError(
                'action_state must be "attack", "skill", or "reload".'
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

        # Starting an attack/skill from dash ends dash movement. A standard
        # reload is different: it is an overlay and must preserve whichever
        # locomotion state (walk/jump/fall/dash) is currently active.
        if runtime.locomotion_state == 'dash' and not preserve_locomotion:
            runtime.dash_active_until = 0.0
            runtime.locomotion_state = 'fall' if not self.is_grounded else 'idle'

        if not preserve_locomotion:
            runtime.action_state = action_state
        runtime.action_locked_until = now + duration_seconds
        runtime.active_action_id = action_id
        runtime.combat_state = max(0, min(4, int(combat_state)))
        runtime.active_action_stagger_immune = bool(stagger_immune)
        runtime.active_action_animation_name = animation_name
        runtime.active_action_animation_playback_speed = max(0.01, playback_speed)
        runtime.animation_name = animation_name
        runtime.animation_elapsed = 0.0
        runtime.animation_playback_speed = runtime.active_action_animation_playback_speed

    def _clear_active_action_metadata(self) -> None:
        runtime = self.party.active_runtime
        runtime.active_action_id = None
        runtime.active_action_stagger_immune = False
        runtime.active_action_animation_name = None
        runtime.active_action_animation_playback_speed = 1.0
        runtime.combat_state = 0

    def _has_active_action_presentation(self, now: float) -> bool:
        """Whether a timed action currently owns the visible animation.

        Standard reload deliberately survives dash/jump/fall. Dash has its own
        short lock, so it must not shorten the reload presentation timer.
        """

        runtime = self.party.active_runtime
        reload_state = runtime.reload
        if reload_state is not None and now < reload_state.complete_at:
            return True

        return (
            runtime.active_action_id is not None
            and now < runtime.action_locked_until
            and runtime.active_action_animation_name is not None
        )

    def _cancel_active_action(self) -> None:
        """Cancel an action without refunding cooldown/ammo or filling reloads.

        This is used by dash, normal hit-stun, and death. A reload's ammunition
        remains at the value it had when cancelled—standard reload is already
        zeroed on start, and R93 must already be empty to start.
        """

        runtime = self.party.active_runtime
        runtime.reload = None
        runtime.action_locked_until = 0.0
        self._clear_active_action_metadata()

    def _cancel_pending_player_effects(self, world: World | None) -> None:
        """Drop unspawned and already spawned player attacks on death.

        The project has one world player, so removing player_projectile is the
        correct strict cancellation behavior for an interrupted death state.
        """

        self._pending_skill_ids.clear()
        self._pending_projectile_requests.clear()
        if world is not None:
            world.remove_all_in_group('player_projectile')

    def consume_pending_skill_ids(self) -> tuple[str, ...]:
        """Return successful actions awaiting PlayScene world spawning."""

        pending = tuple(self._pending_skill_ids)
        self._pending_skill_ids.clear()
        return pending

    def consume_pending_projectile_requests(self) -> tuple[tuple[str, int], ...]:
        """Return delayed projectiles with the direction captured on release."""

        pending = tuple(self._pending_projectile_requests)
        self._pending_projectile_requests.clear()
        return pending

    def take_damage(
        self,
        amount: int,
        app: GameApp,
        world: World | None = None,
    ) -> bool:
        """Apply a hit through dodge, immunity, stagger, and death states.

        * Dash/dodge: collision is rejected before any HP change.
        * Post-hit invulnerability: later hits are ignored entirely.
        * Stagger immunity: HP falls and the 0.5s protection starts, but the
          existing skill/reload state, animation, and pending completion stay.
        * Ordinary action: HP falls, current action is cancelled, then hit-stun.
        * HP zero: all active actions/effects are cancelled and Die overrides
          every other state.
        """

        now = app.timer.game_time
        runtime = self.party.active_runtime
        self.last_damage_outcome = 'none'

        if self.party.shared_hp <= 0 or self.party.is_respawning:
            return False

        if self.is_dodging:
            self.last_damage_outcome = 'dodged'
            return False

        if now < runtime.hit_invulnerable_until:
            self.last_damage_outcome = 'invulnerable'
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
        runtime.hit_invulnerable_until = now + invulnerability_seconds

        if self.party.shared_hp <= 0:
            self._begin_death('hp_zero', now, app, world)
            self.last_damage_outcome = 'dead_hp_zero'
            return True

        if self.has_stagger_immunity:
            # Do not alter action_locked_until, action_state, active skill id,
            # reload runtime, or animation. Damage and protection only.
            self.last_damage_outcome = 'stagger_immune'
            return True

        self._cancel_active_action()
        runtime.action_state = 'hit'
        runtime.action_locked_until = now + invulnerability_seconds
        runtime.animation_name = 'hit'
        runtime.animation_elapsed = 0.0
        runtime.animation_playback_speed = 1.0
        self.last_damage_outcome = 'staggered'
        return True

    def die_from_pit(
        self,
        world: World,
        app: GameApp,
    ) -> bool:
        """Enter the distinct fall-death route without changing HP or XP."""

        if self.party.shared_hp <= 0 or self.party.is_respawning:
            return False

        self._begin_death('pit', app.timer.game_time, app, world)
        self.last_damage_outcome = 'pit_death'
        return True

    def _begin_death(
        self,
        cause: str,
        now: float,
        app: GameApp,
        world: World | None,
    ) -> None:
        """Make death the hard top-priority state.

        No attack, skill, reload, dash, temporary speed modifier, queued effect,
        or active player projectile survives this transition. HP-zero applies a
        configurable experience loss clamped at zero; pit death applies none.
        """

        if self.action_state in ('dead', 'respawn_wait') or self.party.is_respawning:
            return

        if cause == 'hp_zero':
            penalty = int(
                self.party.shared_settings['respawn'].get(
                    'experience_loss_on_hp_zero_death',
                    0,
                )
            )
            self.party.lose_experience(penalty)

        self.party.begin_shared_death(cause)
        self._cancel_pending_player_effects(world)

        runtime = self.party.active_runtime
        death_duration = CharacterSpriteCache.get_animation_duration(
            app,
            self._definition,
            'die',
        )
        runtime.locomotion_state = 'idle'
        runtime.combat_state = 0
        runtime.action_state = 'dead'
        runtime.action_locked_until = now + max(0.0, death_duration or 0.0)
        runtime.animation_name = 'die'
        runtime.animation_elapsed = 0.0
        runtime.animation_playback_speed = 1.0
        runtime.active_action_id = None
        runtime.active_action_stagger_immune = False
        runtime.active_action_animation_name = None
        runtime.active_action_animation_playback_speed = 1.0
        self.velocity_y = 0.0
        self.is_grounded = False
        self._jump_requested = False

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
            # Keep the visible Die motion alive until its final frame. Only then
            # does PartyManager switch the player to invisible respawn_wait.
            if now < runtime.action_locked_until:
                return True
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
            requested = int(effect['amount']) * max(0, int(amount))
            maximum = self.party.active_runtime.max_ammo.get(ammo_type)
            current = self.ammo.get(ammo_type, 0)
            added = requested if maximum is None else max(
                0,
                min(requested, maximum - current),
            )
            self.ammo[ammo_type] = current + added
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
        direction = int(self._right_held) - int(self._left_held)
        now = app.timer.game_time

        if self._update_respawn_state(now, app):
            self._jump_requested = False
            self._update_animation(delta_seconds, direction, now)
            return

        self._advance_reload(now)
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

        runtime = self.party.active_runtime
        reload_state = runtime.reload
        # Reload is intentionally not a movement-blocking combat action. Its
        # sheet overlays locomotion, whereas ordinary attack/skill actions stop
        # horizontal movement and fresh jumps until their lock is over.
        blocking_combat_action_active = (
            runtime.active_action_id is not None and reload_state is None
        )

        if runtime.locomotion_state == 'dash':
            dash_speed = (
                self.move_speed
                * float(
                    self.party.shared_settings['movement'][
                        'dash_speed_multiplier'
                    ]
                )
            )
            self._move_horizontally(
                runtime.dash_direction * dash_speed * delta_seconds,
                world,
            )

        elif (
            reload_state is not None
            and reload_state.mode == 'recoil_projectile'
            and reload_state.released
            and reload_state.recoil_speed > 0.0
        ):
            # R93 recoil reload supplies its own scripted horizontal impulse.
            self._move_horizontally(
                -reload_state.direction * reload_state.recoil_speed * delta_seconds,
                world,
            )

        elif (
            not blocking_combat_action_active
            and not movement_inputs_locked
            and direction != 0
        ):
            # Locomotion is independent from SG standard reload. The reload
            # overlay may run during walking, jumping, or falling, while an
            # actual attack/skill action still intentionally stops horizontal
            # input until its own action lock finishes.
            self.facing = direction
            self._move_horizontally(
                direction * self.move_speed * delta_seconds,
                world,
            )

        can_jump_while_reloading = (
            reload_state is not None and reload_state.mode == 'standard'
        )
        if (
            self._jump_requested
            and self.is_grounded
            and not movement_inputs_locked
            and not blocking_combat_action_active
            and (
                runtime.locomotion_state in ('idle', 'walk')
                or can_jump_while_reloading
            )
        ):
            self.velocity_y = self.jump_speed
            self.is_grounded = False
            self._set_airborne_state('jump')

        self._move_vertically(delta_seconds, world)
        if self._is_below_pit_death_boundary(world):
            self.die_from_pit(world, app)
            self._jump_requested = False
            self._update_animation(delta_seconds, direction, now)
            return

        self._clamp_to_world_bounds(world)

        self._jump_requested = False
        self._update_animation(delta_seconds, direction, now)

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
        self._advance_reload(now)
        self._refresh_temporary_action_state(now)
        runtime = self.party.active_runtime

        if runtime.reload is not None:
            return '장전 중입니다.'

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
            'reload': '장전 중입니다.',
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

    def _finish_dash_locomotion(self) -> None:
        """Release a completed dash back into the current physical movement.

        Dash is a locomotion state as well as a temporary action presentation.
        It must remain intact through vertical physics until its own duration
        ends; otherwise gravity would replace it with ``jump``/``fall`` on the
        same frame that the dash starts.
        """

        runtime = self.party.active_runtime
        if runtime.locomotion_state != 'dash':
            return

        if self.is_grounded:
            # Clear dash as a dodge/reaction state before the grounded setter.
            # A standard reload may still be active as an animation overlay,
            # but it must not keep the player invulnerable after dash ends.
            runtime.locomotion_state = 'idle'
            runtime.action_state = 'idle'
            self._set_grounded_state()
            return

        state = 'jump' if self.velocity_y > 0.0 else 'fall'
        runtime.locomotion_state = state
        runtime.action_state = state
        self._set_airborne_state(state)

    def _refresh_temporary_action_state(self, now: float) -> None:
        runtime = self.party.active_runtime
        reload_state = runtime.reload

        # Reload owns its actual completion time independently of locomotion.
        # A dash can temporarily own locomotion, but it must never shorten a
        # standard reload or clear its animation/action metadata.
        if reload_state is not None:
            if now >= reload_state.complete_at:
                self._finish_reload()
            else:
                if (
                    runtime.locomotion_state == 'dash'
                    and now >= runtime.dash_active_until
                ):
                    self._finish_dash_locomotion()
                return

        # A regular attack/skill may have begun while jumping or falling.
        # Once its action lock ends, release it back to the current physical
        # state instead of leaving an expired animation overlay behind.
        if runtime.active_action_id is not None:
            if now < runtime.action_locked_until:
                return

            self._clear_active_action_metadata()
            if not self.is_grounded:
                state = 'jump' if self.velocity_y > 0.0 else 'fall'
                self._set_airborne_state(state)
                return

            self._set_grounded_state()
            return

        # Dash and ordinary hit-stun have no active action overlay, but still
        # own a short lock in action_state.
        if runtime.action_state not in ('hit', 'dash', 'reload'):
            return

        if now < runtime.action_locked_until:
            return

        if runtime.action_state == 'reload':
            self._finish_reload()

        if runtime.action_state == 'dash':
            self._finish_dash_locomotion()
            return

        # Hit ends only after its 0.5-second lock. Clear the reaction state
        # before applying the physical idle/walk/jump/fall state so the visible
        # Hit sheet is not replaced by gravity or landing in the same frame.
        if runtime.action_state == 'hit':
            runtime.action_state = 'idle'
            runtime.action_locked_until = 0.0

        if not self.is_grounded:
            state = 'jump' if self.velocity_y > 0.0 else 'fall'
            self._set_airborne_state(state)
            return

        self._set_grounded_state()

    def _update_animation(
        self,
        delta_seconds: float,
        direction: int,
        now: float,
    ) -> None:
        runtime = self.party.active_runtime

        # Death and hit-stun are foreground reactions. They must be checked
        # before locomotion because vertical physics still updates while they
        # are active. Without this priority, fall/landing immediately replaced
        # the Die or Hit sheet on the same frame.
        if runtime.action_state == 'dead':
            runtime.animation_name = 'die'
            runtime.animation_playback_speed = 1.0
            runtime.animation_elapsed += delta_seconds
            return

        if runtime.action_state == 'respawn_wait':
            return

        if runtime.action_state == 'hit':
            runtime.animation_name = 'hit'
            runtime.animation_playback_speed = 1.0
            runtime.animation_elapsed += delta_seconds
            return

        # Visual priority intentionally follows the old character state
        # machine: active attack/reload/skill sheets render before locomotion.
        # Reload owns a separate completion timer because dash/jump/fall can
        # temporarily own locomotion without canceling it.
        reload_state = runtime.reload
        if reload_state is not None and now < reload_state.complete_at:
            runtime.animation_name = reload_state.animation_name
            runtime.animation_playback_speed = (
                reload_state.animation_playback_speed
            )
            runtime.animation_elapsed += delta_seconds
            return

        # Jump/fall may still own physics, but cannot reset this elapsed timer.
        if self._has_active_action_presentation(now):
            runtime.animation_name = str(runtime.active_action_animation_name)
            runtime.animation_playback_speed = (
                runtime.active_action_animation_playback_speed
            )
            runtime.animation_elapsed += delta_seconds
            return

        if runtime.locomotion_state in ('idle', 'walk'):
            next_name = 'walk' if direction != 0 else 'idle'
            runtime.locomotion_state = next_name
            runtime.action_state = next_name

            if runtime.animation_name != next_name:
                runtime.animation_name = next_name
                runtime.animation_elapsed = 0.0
                runtime.animation_playback_speed = 1.0
            else:
                runtime.animation_elapsed += delta_seconds
            return

        if runtime.locomotion_state in ('jump', 'fall', 'dash'):
            # All three states hold Walk_## (1).png only when no active action
            # presentation is running above them.
            runtime.animation_name = 'walk'
            runtime.animation_elapsed = 0.0
            runtime.animation_playback_speed = 1.0
            return

        runtime.animation_elapsed += delta_seconds

    def _set_airborne_state(self, state: str) -> None:
        """Update physical jump/fall without canceling foreground state.

        Dash remains a timed locomotion state until ``_finish_dash_locomotion``
        releases it. Hit and death may still receive gravity/landing physics,
        but retain their own visible reaction animation.
        """

        if state not in ('jump', 'fall'):
            raise ValueError('Airborne state must be "jump" or "fall".')

        runtime = self.party.active_runtime
        if runtime.locomotion_state == 'dash':
            return

        runtime.locomotion_state = state

        if (
            runtime.reload is not None
            or runtime.active_action_id is not None
            or runtime.action_state in ('hit', 'dead', 'respawn_wait')
        ):
            return

        runtime.action_state = state
        runtime.animation_name = 'walk'
        runtime.animation_elapsed = 0.0
        runtime.animation_playback_speed = 1.0

    def _set_grounded_state(self) -> None:
        """Update physical idle/walk without restarting foreground actions."""

        runtime = self.party.active_runtime
        if runtime.locomotion_state == 'dash':
            return

        direction = int(self._right_held) - int(self._left_held)
        state = 'walk' if direction != 0 else 'idle'
        runtime.locomotion_state = state

        already_in_same_animation = (
            runtime.action_state == state
            and runtime.animation_name == state
        )

        if (
            runtime.reload is not None
            or runtime.active_action_id is not None
            or runtime.action_state in ('hit', 'dead', 'respawn_wait')
        ):
            return

        runtime.action_state = state
        runtime.animation_name = state

        if already_in_same_animation:
            return

        runtime.animation_elapsed = 0.0
        runtime.animation_playback_speed = 1.0

    def _move_horizontally(
        self,
        movement_x: float,
        world: World,
    ) -> None:
        if movement_x == 0.0:
            return

        previous_left = self.left
        previous_right = self.right
        self.x += movement_x

        # Only tiles crossed by this movement can block it. Querying the
        # terrain grid here replaces the previous full-stage terrain scan.
        query_left = min(previous_left, self.left)
        query_right = max(previous_right, self.right)
        for block in world.terrain_blocks_overlapping_x(
            query_left,
            query_right,
        ):
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
        world: World,
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
            self._resolve_landing(previous_bottom, world)

            # The moment +Y speed reaches zero or becomes negative, the state
            # becomes fall. It remains fall until _resolve_landing() detects a
            # real terrain collision and sets is_grounded.
            if self.is_grounded:
                # Physical landing always updates locomotion. Foreground
                # attack/skill/reload presentation remains untouched.
                self._set_grounded_state()
            else:
                self._set_airborne_state('fall')
            return

        self._resolve_ceiling(previous_top, world)

        # A ceiling impact can set velocity_y to zero. In that case the player
        # begins falling immediately and still stays in fall until landing.
        if self.velocity_y <= 0.0:
            self._set_airborne_state('fall')
        else:
            self._set_airborne_state('jump')

    def _resolve_landing(
        self,
        previous_bottom: float,
        world: World,
    ) -> None:
        landing_block: TerrainBlock | None = None

        # Vertical collision only depends on columns under the player's AABB.
        for block in world.terrain_blocks_overlapping_x(self.left, self.right):
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
        world: World,
    ) -> None:
        ceiling_block: TerrainBlock | None = None

        for block in world.terrain_blocks_overlapping_x(self.left, self.right):
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

    def _is_below_pit_death_boundary(self, world: World) -> bool:
        depth = max(
            0.0,
            float(
                self.party.shared_settings['respawn'].get(
                    'pit_death_depth_below_world_bottom',
                    160.0,
                )
            ),
        )
        # Use the whole collider: the player must fully pass the threshold, not
        # die the instant its feet leave the camera/world bottom.
        return self.top < world.bounds.bottom - depth

    def _clamp_to_world_bounds(self, world: World) -> None:
        bounds = world.bounds
        half_width = self.width * 0.5
        half_height = self.height * 0.5

        if self.left < bounds.left:
            self.x = bounds.left + half_width
        elif self.right > bounds.right:
            self.x = bounds.right - half_width

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
        if self.is_visual_hidden:
            return

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

        action_presentation_active = self._has_active_action_presentation(
            app.timer.game_time
        )
        image = CharacterSpriteCache.get_frame(
            app,
            self._definition,
            resolved_animation_name,
            runtime.animation_elapsed,
            self.facing,
            playback_speed=runtime.animation_playback_speed,
            loop=(
                False
                if action_presentation_active
                else runtime.action_state in ('idle', 'walk', 'dash')
            ),
        )
        rect = camera.rect_from_world_center(
            visual_center_x,
            visual_center_y,
            draw_width,
            draw_height,
        )
        screen.blit(image, rect.topleft)
