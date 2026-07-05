from __future__ import annotations

import random
from typing import TYPE_CHECKING, Any

import pygame

from src.gameplay.enemy_assets import EnemySpriteCache
from src.gameplay.entities.base import Entity

if TYPE_CHECKING:
    from src.app import GameApp
    from src.core.camera import Camera
    from src.core.world import World
    from src.gameplay.entities.player import Player


class Enemy(Entity):
    updates_each_frame = True
    """Static-lane, data-driven monster.

    Enemy source sprites face LEFT. Each spawn begins with a random facing;
    right-facing monsters use the precomputed horizontal flip.

    Enemies never jump or fall. Because this project uses static tile stages,
    the stage builds safe horizontal navigation lanes once. Patrol and pursuit
    then only clamp against precomputed numeric bounds; they do not repeatedly
    probe terrain tiles while walking.
    """

    _EPSILON = 0.01

    # Enemies inside the configured horizontal activity radius update every
    # frame. Static navigation lanes make the 1-second far update safe because
    # patrol/chase movement is clamped to precomputed numeric bounds.
    _DEFAULT_NEAR_AI_HORIZONTAL_RANGE = 1600.0
    _DEFAULT_FAR_AI_INTERVAL_SECONDS = 1.0

    # Original Desperado's useful idea, retained without copying its simpler
    # movement model: calm patrol pressure advances on a separate fixed tick.
    # Terrain safety is already guaranteed by the stage-static navigation lane.
    _DEFAULT_PATROL_LOGIC_TICK_SECONDS = 0.25
    _DEFAULT_ATTACK_CHARGE_TICK_SECONDS = 0.25
    _DEFAULT_ATTACK_CHARGE_PER_TICK = 1.0
    _DEFAULT_ATTACK_CHARGE_REQUIRED = 4.0

    def __init__(
        self,
        enemy_id: str,
        definition: dict[str, Any],
        shared_settings: dict[str, Any],
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
            collision_group='enemy',
        )

        self.enemy_id = enemy_id
        self.display_name = str(definition['display_name'])
        self.definition = definition
        self.color = tuple(visual['placeholder_color'])

        stats = definition['stats']
        self.max_hp = int(stats['max_hp'])
        self.hp = self.max_hp
        self.move_speed = max(0.0, float(stats['move_speed']))
        self.fortitude = max(0.0, float(stats.get('fortitude', 0.0)))

        # These timings are deliberately stage-wide rules. Per-enemy damage
        # remains data driven, but every enemy shares the same contact cadence
        # and post-hit protection so balancing them cannot silently drift.
        self.contact_damage = max(0, int(stats.get('contact_damage', 0)))
        self.contact_cooldown_seconds = max(
            0.0,
            float(shared_settings['contact_cooldown_seconds']),
        )
        self.hit_invulnerability_seconds = max(
            0.0,
            float(shared_settings['hit_invulnerability_seconds']),
        )
        # AI activity is shared by every monster. The range is horizontal only:
        # ±1600 px updates every frame; every farther enemy uses the far tick.
        self._near_ai_horizontal_range = max(
            0.0,
            float(
                shared_settings.get(
                    'near_ai_horizontal_range',
                    self._DEFAULT_NEAR_AI_HORIZONTAL_RANGE,
                )
            ),
        )
        self._far_ai_interval_seconds = max(
            0.05,
            float(
                shared_settings.get(
                    'far_ai_interval_seconds',
                    self._DEFAULT_FAR_AI_INTERVAL_SECONDS,
                )
            ),
        )
        self._contact_ready_at = 0.0

        shared_attack_charge = shared_settings['attack_charge']
        self._attack_charge_tick_seconds = max(
            0.05,
            float(
                shared_attack_charge.get(
                    'logic_tick_seconds',
                    self._DEFAULT_ATTACK_CHARGE_TICK_SECONDS,
                )
            ),
        )
        self._attack_charge_per_tick = max(
            0.0,
            float(
                shared_attack_charge.get(
                    'charge_per_tick',
                    self._DEFAULT_ATTACK_CHARGE_PER_TICK,
                )
            ),
        )
        self._attack_charge_required = max(
            self._EPSILON,
            float(
                shared_attack_charge.get(
                    'charge_required',
                    self._DEFAULT_ATTACK_CHARGE_REQUIRED,
                )
            ),
        )

        ui = definition['ui']
        self.hp_show_distance = max(
            0.0,
            float(shared_settings['hp_show_distance']),
        )
        self.hp_bar_offset_y = int(ui.get('hp_bar_offset_y', 12))

        ai = definition['ai']
        patrol = ai['patrol']
        shared_patrol = shared_settings['patrol']
        detection = ai['detection_range_tiles']
        pursuit = ai['pursuit']

        self.temperament = str(ai['temperament'])
        self.patrol_range_tiles = max(0.0, float(patrol['range_tiles']))
        # Patrol decisions are a shared fixed-tick system. A monster only
        # keeps its range, pause duration, and post-Idle turning personality.
        # The pressure curve itself is one authoritative game rule.
        self._patrol_logic_tick_seconds = max(
            0.05,
            float(
                shared_patrol.get(
                    'logic_tick_seconds',
                    self._DEFAULT_PATROL_LOGIC_TICK_SECONDS,
                )
            ),
        )
        self._patrol_pause_min = max(
            0.0,
            float(patrol['pause_min_seconds']),
        )
        self._patrol_pause_max = max(
            self._patrol_pause_min,
            float(patrol['pause_max_seconds']),
        )
        self._wander_turn_pressure_per_tick = max(
            0.0,
            float(shared_patrol['wander_pressure_per_tick']),
        )
        self._wander_turn_pressure_cap = max(
            self._EPSILON,
            float(shared_patrol['wander_pressure_cap']),
        )
        self._wander_idle_probability_steps = tuple(
            (
                float(step['minimum_pressure']),
                float(step['idle_probability']),
            )
            for step in shared_patrol['idle_probability_steps']
        )
        # All enemies share the same post-Idle direction choice.
        # Individual monster behavior differs through patrol range, pause time,
        # movement speed, detection, pursuit, and combat settings instead.
        self._wander_turn_probability_after_idle = min(
            1.0,
            max(
                0.0,
                float(shared_patrol['reverse_probability_after_idle']),
            ),
        )
        self.detect_tiles_x = max(0.0, float(detection['horizontal']))
        self.detect_tiles_y = max(0.0, float(detection['vertical']))

        self.anger_on_hit = max(0.0, float(pursuit['anger_on_hit']))
        self.anger_gain_per_second_in_detection = max(
            0.0,
            float(pursuit['anger_gain_per_second_in_detection']),
        )
        self.anger_decay_per_second_outside_range = max(
            0.0,
            float(pursuit['anger_decay_per_second_outside_range']),
        )
        self.pursue_outside_patrol_threshold = max(
            0.0,
            float(pursuit['pursue_outside_patrol_threshold']),
        )
        self.return_to_patrol_threshold = max(
            0.0,
            float(pursuit['return_to_patrol_threshold']),
        )
        self.max_chase_range_tiles = max(
            0.0,
            float(pursuit['max_chase_range_tiles']),
        )

        combat = definition['combat']
        attack_range = combat['attack_range_tiles']
        self.attack_tiles_x = max(0.0, float(attack_range['horizontal']))
        self.attack_tiles_y = max(0.0, float(attack_range['vertical']))
        self.attack_skill_ids = tuple(
            str(skill_id)
            for skill_id in combat.get('attack_skill_ids', [])
            if isinstance(skill_id, str) and skill_id.strip()
        )
        self.attack_selection_weights = {
            str(skill_id): max(0.0, float(weight))
            for skill_id, weight in combat.get(
                'attack_selection_weights',
                {},
            ).items()
            if str(skill_id) in self.attack_skill_ids
        }

        respawn = definition['respawn']
        self._respawn_min_seconds = max(
            0.0,
            float(respawn['min_seconds']),
        )
        self._respawn_max_seconds = max(
            self._respawn_min_seconds,
            float(respawn['max_seconds']),
        )

        # Home is immutable: respawn and patrol always use this original spawn.
        self.spawn_x = float(x)
        self.spawn_y = float(y)
        self._surface_top = self.bottom
        self._tile_size = 40.0

        # Filled once from World static navigation after terrain is committed.
        # The lane contains the only legal horizontal positions for this exact
        # collider size, so patrol never needs runtime wall/pit checks.
        self._navigation_revision = -1
        self._navigation_lane_id: int | None = None
        self._navigation_left = self.x
        self._navigation_right = self.x
        self._patrol_left = self.x
        self._patrol_right = self.x
        self._chase_left = self.x
        self._chase_right = self.x
        self._navigation_ready = False
        self._navigation_warning_keys: set[tuple[int, str]] = set()

        # Enemy source art faces LEFT; every spawn randomly faces either way.
        self.facing = random.choice((-1, 1))
        self._patrol_direction = self.facing
        self._patrol_logic_elapsed = 0.0
        self._patrol_pause_until = 0.0
        self._patrol_wait_reason: str | None = None
        self._patrol_wait_turn_probability = 0.0
        self._patrol_turn_pressure = 0.0

        self.anger = 0.0
        self._pursuit_committed = False
        self._blocked_chase = False
        # Normal patrol is allowed to move away from spawn. This flag becomes
        # true only after a real chase has ended. The enemy first plays one
        # Idle pass, then returns only to the patrol *area* if it is outside.
        self._was_chasing = False
        self._returning_to_patrol_area = False

        self.action_state = 'idle'
        self.animation_elapsed = 0.0
        self._hit_until = 0.0
        self._stunned_until = 0.0
        self._stun_total_duration = 0.0
        self._attack_locked_until = 0.0
        self._attack_charge_elapsed = 0.0
        self._attack_charge_value = 0.0
        self._skill_ready_at: dict[str, float] = {}
        # Death plays once before the entity becomes an invisible respawn wait.
        # Respawn timing starts only after this visual pass has finished.
        self._death_animation_ends_at = 0.0
        self._respawn_ready_at = 0.0

        self._experience_claimed = False

        # Time accumulated while this enemy is outside the player's immediate
        # activity area. It is consumed by the same AI routine, so state rules
        # remain identical while distant actors perform fewer decisions.
        self._ai_elapsed = 0.0

        # These ranges are derived from immutable enemy data and the stage tile
        # size. Cache them instead of rebuilding several max() expressions for
        # every nearby enemy every frame.
        self._ai_range_tile_size: float | None = None
        self._patrol_range_pixels_value = 0.0
        self._max_chase_range_pixels_value = 0.0
        self._detect_range_x_pixels = 0.0
        self._detect_range_y_pixels = 0.0
        self._attack_range_x_pixels = 0.0
        self._attack_range_y_pixels = 0.0
        self._hp_show_distance_squared = self.hp_show_distance * self.hp_show_distance

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

    @property
    def is_defeated(self) -> bool:
        return self.hp <= 0

    @property
    def is_hit(self) -> bool:
        return self.action_state == 'hit'

    @property
    def is_respawn_waiting(self) -> bool:
        return self.is_defeated

    @property
    def is_visual_hidden(self) -> bool:
        """Hide sprite and all debug geometry after Die has completed."""

        return self.action_state == 'respawn_wait'

    def can_be_targeted_by_player(self, now: float) -> bool:
        """Hit monsters are temporarily removed from player-hit target lists.

        Stunned monsters intentionally remain targetable; they cannot act but
        the player can keep attacking them.
        """

        return (
            not self.is_defeated
            and self.action_state != 'hit'
            and now >= self._hit_until
        )

    def take_damage(self, damage: int, app: GameApp) -> bool:
        """Deal player damage and start hit invulnerability / anger."""

        now = app.timer.game_time
        if not self.can_be_targeted_by_player(now):
            return False

        amount = max(0, int(damage))
        if amount <= 0:
            return False

        self.hp = max(0, self.hp - amount)
        self.anger += self.anger_on_hit
        self._pursuit_committed = (
            self._pursuit_committed
            or self.anger >= self.pursue_outside_patrol_threshold
        )

        if self.hp <= 0:
            self._begin_death(now, app)
            return True

        self._hit_until = now + self.hit_invulnerability_seconds
        self._reset_attack_charge()
        self._set_action('hit', restart_animation=True)
        return True

    def apply_stun(self, duration_seconds: float, app: GameApp) -> bool:
        """Apply a Fortitude-reduced stun using Hit_## (1).png."""

        now = app.timer.game_time
        if not self.can_be_targeted_by_player(now):
            return False

        base_duration = max(0.0, float(duration_seconds))
        if base_duration <= 0.0:
            return False

        actual_duration = base_duration * 100.0 / (100.0 + self.fortitude)
        remaining = max(0.0, self._stunned_until - now)
        combined_duration = max(remaining, actual_duration)
        self._stunned_until = now + combined_duration
        self._stun_total_duration = combined_duration
        self._reset_attack_charge()
        self._set_action('stun', restart_animation=True)
        return True

    def is_stunned(self, now: float) -> bool:
        return now < self._stunned_until

    def can_contact_attack(self, now: float) -> bool:
        return (
            not self.is_defeated
            and self.action_state != 'hit'
            and not self.is_stunned(now)
            and self.contact_damage > 0
            and now >= self._contact_ready_at
        )

    def mark_contact_attack(self, now: float) -> None:
        self._contact_ready_at = now + self.contact_cooldown_seconds

    def claim_experience_reward(self) -> int:
        if not self.is_defeated or self._experience_claimed:
            return 0

        self._experience_claimed = True
        rewards = self.definition.get('rewards', {})
        return max(0, int(rewards.get('experience_reward', 0)))

    def can_target_player(self, player: Player | None) -> bool:
        return (
            player is not None
            and not player.is_stealthed
            and not player.party.is_respawning
            and player.hp > 0
        )

    def is_near_player(self, player: Player | None) -> bool:
        if player is None:
            return False

        dx = player.x - self.x
        dy = player.y - self.y
        return dx * dx + dy * dy <= self._hp_show_distance_squared

    def draw_debug_ranges(
        self,
        screen: pygame.Surface,
        camera: Camera,
    ) -> None:
        """Draw green detection and orange attack ranges from the body base.

        Horizontal values are half-extents measured from the enemy center.
        Vertical values are full heights measured upward from the enemy hitbox
        bottom, matching the bottom-left world coordinate convention.
        """

        self._draw_debug_rectangle(
            screen,
            camera,
            self._detect_range_x_pixels,
            self._detect_range_y_pixels,
            (42, 220, 82),
        )
        self._draw_debug_rectangle(
            screen,
            camera,
            self._attack_range_x_pixels,
            self._attack_range_y_pixels,
            (255, 157, 42),
        )

    def _draw_debug_rectangle(
        self,
        screen: pygame.Surface,
        camera: Camera,
        horizontal_radius: float,
        vertical_height: float,
        color: tuple[int, int, int],
    ) -> None:
        if horizontal_radius <= 0.0 or vertical_height <= 0.0:
            return

        width = horizontal_radius * 2.0
        height = vertical_height
        center_y = self.bottom + height * 0.5
        if not camera.is_world_rect_visible(self.x, center_y, width, height):
            return

        rect = camera.rect_from_world_center(
            self.x,
            center_y,
            width,
            height,
        )
        pygame.draw.rect(screen, color, rect, width=2)

    def initialize_navigation(self, world: World) -> None:
        """Bind this enemy to the stage's precomputed static lane.

        PlayScene calls this after terrain and enemy spawns are committed. The
        same method is safe after a terrain rebuild: only then does it inspect
        a new navigation map, never individual terrain tiles per frame.
        """

        self._initialize_navigation(world)

    def _initialize_navigation(self, world: World) -> None:
        revision = world.terrain_navigation_revision
        if self._navigation_revision == revision:
            return

        self._tile_size = world.terrain_tile_size
        self._refresh_ai_activity_ranges()
        lane = world.navigation_lane_for_body(
            x=self.x,
            body_bottom=self.bottom,
            width=self.width,
            height=self.height,
            allow_spawn_tolerance=True,
        )
        self._navigation_revision = revision
        self._navigation_lane_id = None
        self._navigation_ready = False

        if lane is None:
            self._navigation_left = self.x
            self._navigation_right = self.x
            self._patrol_left = self.x
            self._patrol_right = self.x
            self._chase_left = self.x
            self._chase_right = self.x
            self._warn_invalid_navigation(
                revision,
                '스폰 발밑에 이 몬스터 크기가 걸을 수 있는 연속 지형이 없습니다.',
            )
            return

        self._navigation_ready = True
        self._navigation_lane_id = lane.lane_id
        self._navigation_left = lane.center_left
        self._navigation_right = lane.center_right
        self._surface_top = lane.surface_top
        self.y = self._surface_top + self.height * 0.5

        requested_patrol_left = self.spawn_x - self._patrol_range_pixels
        requested_patrol_right = self.spawn_x + self._patrol_range_pixels
        self._patrol_left = max(self._navigation_left, requested_patrol_left)
        self._patrol_right = min(self._navigation_right, requested_patrol_right)

        if self._patrol_left > self._patrol_right + self._EPSILON:
            self._patrol_left = min(
                max(self.spawn_x, self._navigation_left),
                self._navigation_right,
            )
            self._patrol_right = self._patrol_left
            self._warn_invalid_navigation(
                revision,
                '설정한 배회 범위 안에 이 몬스터가 설 수 있는 구간이 없습니다.',
            )
        elif (
            self._patrol_left > requested_patrol_left + self._EPSILON
            or self._patrol_right < requested_patrol_right - self._EPSILON
        ):
            self._warn_invalid_navigation(
                revision,
                '배회 범위가 벽·구멍 또는 레인 끝과 겹쳐 실제 안전 구간으로 자동 축소되었습니다.',
            )

        self._chase_left = max(
            self._navigation_left,
            self.spawn_x - self._max_chase_range_pixels,
        )
        self._chase_right = min(
            self._navigation_right,
            self.spawn_x + self._max_chase_range_pixels,
        )
        self.x = min(max(self.x, self._navigation_left), self._navigation_right)

    def _warn_invalid_navigation(self, revision: int, detail: str) -> None:
        key = (revision, detail)
        if key in self._navigation_warning_keys:
            return
        self._navigation_warning_keys.add(key)
        print(
            '[Stage Navigation Warning] '
            f'{self.display_name} ({self.enemy_id}) at x={self.spawn_x:.1f}: {detail}'
        )

    def update(
        self,
        delta_seconds: float,
        world: World,
        app: GameApp,
    ) -> None:
        """Advance enemy logic with frame-near and 1-second-far cadence.

        Near enemies inside the configured horizontal range update every frame
        for immediate combat response. Far enemies outside that range keep the
        requested low-frequency cadence. Death motion and its transition into
        hidden respawn wait remain frame-accurate so a Die sheet never freezes
        while a distant AI tick is waiting.
        """

        now = app.timer.game_time

        if self.is_defeated:
            self._update_respawn(delta_seconds, now, world)
            return

        self._tile_size = world.terrain_tile_size
        self._refresh_ai_activity_ranges()
        self._initialize_navigation(world)

        player = world.primary_player
        if player is not None and abs(player.x - self.x) <= self._near_ai_horizontal_range:
            self._ai_elapsed = 0.0
            self._update_ai(delta_seconds, world, app, now, player)
            return

        interval = self._far_ai_interval_seconds
        self._ai_elapsed += delta_seconds
        if self._ai_elapsed + self._EPSILON < interval:
            return

        # Keep the fractional remainder, but execute no burst catch-up loop.
        # This preserves the requested fixed cadence and avoids a long frame
        # causing one enemy to run several expensive decisions at once.
        self._ai_elapsed = max(0.0, self._ai_elapsed - interval)
        self._update_ai(interval, world, app, now, player)

    def _refresh_ai_activity_ranges(self) -> None:
        if self._ai_range_tile_size == self._tile_size:
            return

        self._patrol_range_pixels_value = self.patrol_range_tiles * self._tile_size
        self._max_chase_range_pixels_value = self.max_chase_range_tiles * self._tile_size
        self._detect_range_x_pixels = self.detect_tiles_x * self._tile_size
        self._detect_range_y_pixels = self.detect_tiles_y * self._tile_size
        self._attack_range_x_pixels = self.attack_tiles_x * self._tile_size
        self._attack_range_y_pixels = self.attack_tiles_y * self._tile_size

        self._ai_range_tile_size = self._tile_size

    def _update_ai(
        self,
        delta_seconds: float,
        world: World,
        app: GameApp,
        now: float,
        player: Player | None,
    ) -> None:
        if self.is_stunned(now):
            self._reset_attack_charge()
            self._set_action('stun')
            return

        self._stun_total_duration = 0.0

        if self.action_state == 'hit':
            self._reset_attack_charge()
            if now < self._hit_until:
                return
            self._set_action('idle', restart_animation=True)

        if self.action_state == 'attack':
            if now < self._attack_locked_until:
                self.animation_elapsed += delta_seconds
                return
            self._set_action('idle', restart_animation=True)

        if not self._navigation_ready:
            self._reset_attack_charge()
            self._decay_anger(delta_seconds)
            self._set_action('idle')
            return

        if not self.can_target_player(player):
            self._reset_attack_charge()
            self._decay_anger(delta_seconds)
            if (
                self._was_chasing
                or self._pursuit_committed
                or self._blocked_chase
            ):
                self._begin_post_chase_idle_wait(now, app)
            self._return_or_patrol(delta_seconds, app, now)
            return

        assert player is not None
        player_lane_id = world.player_navigation_lane_id_for_profile(
            self.width,
            self.height,
        )
        same_navigation_lane = (
            self._navigation_lane_id is not None
            and player_lane_id == self._navigation_lane_id
        )
        in_detection = self._is_player_in_detection(player)
        in_home_patrol_band = (
            self._patrol_left - self._EPSILON
            <= player.x
            <= self._patrol_right + self._EPSILON
        )

        if self.temperament == 'aggressive' and in_detection and same_navigation_lane:
            self.anger += (
                self.anger_gain_per_second_in_detection * delta_seconds
            )

        self._pursuit_committed = (
            self._pursuit_committed
            or self.anger >= self.pursue_outside_patrol_threshold
        )

        if self.temperament == 'aggressive':
            chase_base_allowed = in_detection
        else:
            chase_base_allowed = self.anger > 0.0 and in_home_patrol_band

        if (
            self._pursuit_committed
            and self._chase_left - self._EPSILON
            <= player.x
            <= self._chase_right + self._EPSILON
        ):
            chase_base_allowed = True

        # Different lanes replace the old expensive full path scan. The enemy
        # cannot jump/fall between lanes, so it must not pursue; anger decays
        # instead of leaving a hidden blocked-chase loop running.
        if not same_navigation_lane:
            self._reset_attack_charge()
            # A player who was never reachable must not force this enemy into an
            # endless post-chase Idle loop. Only a chase that actually began
            # (or was committed by anger) receives the one-pass release Idle.
            had_active_pursuit = (
                self._was_chasing
                or self._pursuit_committed
                or self._blocked_chase
            )
            if had_active_pursuit:
                self._blocked_chase = True

            self._decay_anger(delta_seconds)
            if (
                had_active_pursuit
                and self.anger <= self.return_to_patrol_threshold
            ):
                self._begin_post_chase_idle_wait(now, app)
            self._return_or_patrol(delta_seconds, app, now)
            return

        if not in_detection and self.temperament == 'aggressive':
            self._decay_anger(delta_seconds)
        elif self.temperament == 'passive' and not in_home_patrol_band:
            self._decay_anger(delta_seconds)

        if (
            chase_base_allowed
            and self.anger >= self.return_to_patrol_threshold
        ):
            self._cancel_patrol_idle_wait()
            self._reset_patrol_pressure()
            self._blocked_chase = False
            self._was_chasing = True
            self._returning_to_patrol_area = False

            if self._can_charge_attack(player, now):
                self._face_player(player)
                if self._advance_attack_charge(delta_seconds):
                    self._start_attack(now, world, app, player)
                    return

                # Charging keeps the enemy still and facing the target. It uses
                # Idle art until the shared 0.25-second gauge reaches its cost.
                self._set_action('idle')
                self.animation_elapsed += delta_seconds
                return

            self._reset_attack_charge()
            target_x = min(max(player.x, self._chase_left), self._chase_right)
            moved = self._move_toward_x(
                target_x,
                delta_seconds,
                minimum_x=self._chase_left,
                maximum_x=self._chase_right,
            )
            if not moved:
                self._decay_anger(delta_seconds)
                self._set_action('idle')
            return

        if self.anger <= self.return_to_patrol_threshold and (
            self._was_chasing
            or self._blocked_chase
            or self._pursuit_committed
        ):
            self._begin_post_chase_idle_wait(now, app)

        self._return_or_patrol(delta_seconds, app, now)

    @property
    def _patrol_range_pixels(self) -> float:
        return self._patrol_range_pixels_value

    @property
    def _max_chase_range_pixels(self) -> float:
        return self._max_chase_range_pixels_value

    def _is_player_in_detection(self, player: Player) -> bool:
        return self._is_player_in_base_anchored_range(
            player,
            self._detect_range_x_pixels,
            self._detect_range_y_pixels,
        )

    def _is_player_in_attack_range(self, player: Player) -> bool:
        return self._is_player_in_base_anchored_range(
            player,
            self._attack_range_x_pixels,
            self._attack_range_y_pixels,
        )

    def _is_player_in_base_anchored_range(
        self,
        player: Player,
        horizontal_radius: float,
        vertical_height: float,
    ) -> bool:
        """Test the exact base-anchored rectangle shown by H-debug.

        A horizontal value of 10 reaches 10 px left and right from enemy.x.
        A vertical value of 10 starts at this enemy's hitbox bottom and reaches
        10 px upward. The player hitbox bottom is the Y test point, so actors
        standing on the same ground use the same base coordinate.
        """

        if horizontal_radius <= 0.0 or vertical_height <= 0.0:
            return False

        if abs(player.x - self.x) > horizontal_radius:
            return False

        range_bottom = self.bottom
        range_top = range_bottom + vertical_height
        return range_bottom <= player.bottom <= range_top

    def _can_charge_attack(
        self,
        player: Player,
        now: float,
    ) -> bool:
        """Return whether an in-range enemy may charge its next attack."""

        if not self.attack_skill_ids:
            return False

        if not self._is_player_in_attack_range(player):
            return False

        if (
            self.temperament == 'passive'
            and self.anger < self.return_to_patrol_threshold
        ):
            return False

        return any(
            now >= self._skill_ready_at.get(skill_id, 0.0)
            for skill_id in self.attack_skill_ids
        )

    def _advance_attack_charge(self, delta_seconds: float) -> bool:
        """Add shared attack gauge points on the fixed charge tick."""

        self._attack_charge_elapsed += max(0.0, delta_seconds)
        tick = self._attack_charge_tick_seconds
        available_ticks = int(
            (self._attack_charge_elapsed + self._EPSILON) / tick
        )
        if available_ticks <= 0:
            return False

        # At most four ticks are consumed in one frame. This prevents a long
        # hitch from producing an unbounded catch-up loop while still allowing
        # the requested four-point, one-second Stone Golem wind-up.
        ticks_to_apply = min(4, available_ticks)
        self._attack_charge_elapsed -= ticks_to_apply * tick
        self._attack_charge_value = min(
            self._attack_charge_required,
            self._attack_charge_value
            + self._attack_charge_per_tick * ticks_to_apply,
        )
        return self._attack_charge_value + self._EPSILON >= self._attack_charge_required

    def _reset_attack_charge(self) -> None:
        self._attack_charge_elapsed = 0.0
        self._attack_charge_value = 0.0

    def _face_player(self, player: Player) -> None:
        delta_x = player.x - self.x
        if abs(delta_x) > self._EPSILON:
            self.facing = 1 if delta_x > 0.0 else -1

    def _start_attack(
        self,
        now: float,
        world: World,
        app: GameApp,
        player: Player,
    ) -> None:
        skill_id = self._choose_attack_skill(now)
        if skill_id is None:
            self._reset_attack_charge()
            return

        self._face_player(player)
        skill = app.data.record('skills', skill_id)
        cooldown = max(0.0, float(skill.get('cooldown_seconds', 0.0)))
        duration = max(
            0.0,
            float(skill.get('action_duration_seconds', 0.0)),
        )

        self._skill_ready_at[skill_id] = now + cooldown
        self._attack_locked_until = now + duration
        self._reset_attack_charge()
        self._set_action('attack', restart_animation=True)
        world.queue_enemy_attack(self, skill_id, self.facing)

    def _choose_attack_skill(self, now: float) -> str | None:
        available = tuple(
            skill_id
            for skill_id in self.attack_skill_ids
            if now >= self._skill_ready_at.get(skill_id, 0.0)
        )
        if not available:
            return None

        weights = [
            self.attack_selection_weights.get(skill_id, 1.0)
            for skill_id in available
        ]

        if not any(weight > 0.0 for weight in weights):
            return available[0]

        return random.choices(available, weights=weights, k=1)[0]

    def _return_or_patrol(
        self,
        delta_seconds: float,
        app: GameApp,
        now: float,
    ) -> None:
        """Finish post-chase Idle, return to patrol bounds, then wander."""

        if self._advance_patrol_idle_wait(delta_seconds, now):
            return

        if self._returning_to_patrol_area:
            target_x = min(max(self.x, self._patrol_left), self._patrol_right)
            if abs(target_x - self.x) > self._EPSILON:
                self._move_toward_x(
                    target_x,
                    delta_seconds,
                    minimum_x=self._patrol_left,
                    maximum_x=self._patrol_right,
                )
                return

            self._returning_to_patrol_area = False
            self._reset_patrol_pressure()
            self.facing = self._patrol_direction

        self._update_patrol(delta_seconds, app, now)

    def _update_patrol(
        self,
        delta_seconds: float,
        app: GameApp,
        now: float,
    ) -> None:
        """Move only inside precomputed patrol bounds; no tile probes occur."""

        if self._advance_patrol_logic(delta_seconds, now, app):
            return

        if self._patrol_right - self._patrol_left <= self._EPSILON:
            self._set_action('idle')
            return

        candidate_x = self.x + self._patrol_direction * self.move_speed * delta_seconds
        if candidate_x <= self._patrol_left:
            self.x = self._patrol_left
            self._reverse_patrol_direction()
            self._set_action('idle')
            return
        if candidate_x >= self._patrol_right:
            self.x = self._patrol_right
            self._reverse_patrol_direction()
            self._set_action('idle')
            return

        self.x = candidate_x
        self.facing = self._patrol_direction
        self._set_action('walk')
        self.animation_elapsed += delta_seconds

    def _advance_patrol_logic(
        self,
        delta_seconds: float,
        now: float,
        app: GameApp,
    ) -> bool:
        """Advance quiet patrol pressure only on the fixed original-style tick."""

        self._patrol_logic_elapsed += delta_seconds
        tick = self._patrol_logic_tick_seconds
        available_ticks = int(
            (self._patrol_logic_elapsed + self._EPSILON) / tick
        )
        if available_ticks <= 0:
            return False

        ticks_to_apply = min(4, available_ticks)
        self._patrol_logic_elapsed -= ticks_to_apply * tick

        for _ in range(ticks_to_apply):
            self._patrol_turn_pressure = min(
                self._wander_turn_pressure_cap,
                self._patrol_turn_pressure
                + self._wander_turn_pressure_per_tick,
            )
            idle_probability = self._idle_probability_for_pressure(
                self._patrol_turn_pressure,
            )
            if idle_probability > 0.0 and random.random() < idle_probability:
                self._begin_patrol_idle_wait(
                    now,
                    app,
                    reason='wander',
                    turn_probability=(
                        self._wander_turn_probability_after_idle
                    ),
                )
                return True

        return False

    def _idle_probability_for_pressure(self, pressure: float) -> float:
        """Return the highest matching shared Idle probability tier."""

        probability = 0.0
        for minimum_pressure, candidate_probability in (
            self._wander_idle_probability_steps
        ):
            if pressure + self._EPSILON < minimum_pressure:
                break
            probability = candidate_probability
        return probability

    def _begin_patrol_idle_wait(
        self,
        now: float,
        app: GameApp,
        *,
        reason: str,
        turn_probability: float = 0.0,
    ) -> None:
        if self._patrol_wait_reason is not None:
            return

        # Idle is a looping animation, so pause_min/max are the real
        # gameplay duration. They must not be replaced by one art cycle.
        duration = max(
            self._EPSILON,
            random.uniform(
                self._patrol_pause_min,
                self._patrol_pause_max,
            ),
        )

        self._patrol_pause_until = now + duration
        self._patrol_wait_reason = reason
        self._patrol_wait_turn_probability = min(
            1.0,
            max(0.0, turn_probability),
        )
        self._reset_patrol_pressure()
        self._set_action('idle', restart_animation=True)

    def _advance_patrol_idle_wait(
        self,
        delta_seconds: float,
        now: float,
    ) -> bool:
        reason = self._patrol_wait_reason
        if reason is None:
            return False

        if now < self._patrol_pause_until:
            self._set_action('idle')
            self.animation_elapsed += delta_seconds
            return True

        turn_probability = self._patrol_wait_turn_probability
        self._patrol_wait_reason = None
        self._patrol_wait_turn_probability = 0.0
        self._patrol_pause_until = 0.0

        if reason == 'wander':
            if random.random() < turn_probability:
                self._reverse_patrol_direction()
            else:
                self.facing = self._patrol_direction
            return False

        if reason == 'post_chase':
            self._returning_to_patrol_area = not self._is_inside_patrol_area()
            self.facing = self._patrol_direction

        return False

    def _cancel_patrol_idle_wait(self) -> None:
        self._patrol_pause_until = 0.0
        self._patrol_wait_reason = None
        self._patrol_wait_turn_probability = 0.0

    def _reset_patrol_pressure(self) -> None:
        self._patrol_turn_pressure = 0.0
        self._patrol_logic_elapsed = 0.0

    def _begin_post_chase_idle_wait(
        self,
        now: float,
        app: GameApp,
    ) -> None:
        self._was_chasing = False
        self._pursuit_committed = False
        self._blocked_chase = False
        self._returning_to_patrol_area = False
        self._reset_patrol_pressure()
        self._begin_patrol_idle_wait(now, app, reason='post_chase')

    def _is_inside_patrol_area(self) -> bool:
        return (
            self._patrol_left - self._EPSILON
            <= self.x
            <= self._patrol_right + self._EPSILON
        )

    def _reverse_patrol_direction(self) -> None:
        self._patrol_direction *= -1
        self.facing = self._patrol_direction
        self._reset_patrol_pressure()

    def _move_toward_x(
        self,
        target_x: float,
        delta_seconds: float,
        *,
        minimum_x: float,
        maximum_x: float,
    ) -> bool:
        delta = target_x - self.x
        if abs(delta) <= self._EPSILON:
            self._set_action('idle')
            return False

        direction = 1 if delta > 0.0 else -1
        self.facing = direction
        distance = min(abs(delta), self.move_speed * delta_seconds)
        candidate_x = self.x + direction * distance
        candidate_x = min(max(candidate_x, minimum_x), maximum_x)

        if abs(candidate_x - self.x) <= self._EPSILON:
            self._set_action('idle')
            return False

        self.x = candidate_x
        self._set_action('walk')
        self.animation_elapsed += delta_seconds
        return True

    def _decay_anger(self, delta_seconds: float) -> None:
        self.anger = max(
            0.0,
            self.anger
            - self.anger_decay_per_second_outside_range * delta_seconds,
        )

    def _begin_death(self, now: float, app: GameApp) -> None:
        # The death sheet is non-looping. The hidden respawn wait does not start
        # until its final frame has been on screen for the configured duration.
        death_duration = max(
            0.0,
            EnemySpriteCache.get_animation_duration(
                app,
                self.definition,
                'die',
            ),
        )
        self._death_animation_ends_at = now + death_duration
        self._respawn_ready_at = 0.0
        self._contact_ready_at = float('inf')
        self._stunned_until = 0.0
        self._stun_total_duration = 0.0
        self._hit_until = 0.0
        self._ai_elapsed = 0.0
        self._reset_attack_charge()
        self._reset_patrol_pressure()
        self._cancel_patrol_idle_wait()
        self._pursuit_committed = False
        self._blocked_chase = False
        self._was_chasing = False
        self._returning_to_patrol_area = False
        self._set_action('dead', restart_animation=True)

    def _update_respawn(
        self,
        delta_seconds: float,
        now: float,
        world: World,
    ) -> None:
        if self.action_state == 'dead':
            self.animation_elapsed += delta_seconds
            if now + self._EPSILON < self._death_animation_ends_at:
                return

            self._respawn_ready_at = now + random.uniform(
                self._respawn_min_seconds,
                self._respawn_max_seconds,
            )
            self._set_action('respawn_wait', restart_animation=True)
            return

        if now < self._respawn_ready_at:
            return

        self.hp = self.max_hp
        self.x = self.spawn_x
        self.y = self.spawn_y
        self._navigation_revision = -1
        self._initialize_navigation(world)

        self.facing = random.choice((-1, 1))
        self._patrol_direction = self.facing
        self._cancel_patrol_idle_wait()
        self._reset_patrol_pressure()

        self.anger = 0.0
        self._pursuit_committed = False
        self._blocked_chase = False
        self._was_chasing = False
        self._returning_to_patrol_area = False

        self._hit_until = 0.0
        self._stunned_until = 0.0
        self._attack_locked_until = 0.0
        self._reset_attack_charge()
        self._skill_ready_at.clear()
        self._contact_ready_at = 0.0
        self._death_animation_ends_at = 0.0
        self._respawn_ready_at = 0.0
        self._experience_claimed = False
        self._ai_elapsed = 0.0
        self._set_action('idle', restart_animation=True)

    def _set_action(
        self,
        state: str,
        *,
        restart_animation: bool = False,
    ) -> None:
        if self.action_state != state or restart_animation:
            self.action_state = state
            self.animation_elapsed = 0.0
        else:
            self.action_state = state

    def draw(
        self,
        screen: pygame.Surface,
        world: World,
        app: GameApp,
        camera: Camera,
    ) -> None:
        if self.is_visual_hidden:
            return

        animation_name = self.action_state
        force_first_frame = animation_name in ('hit', 'stun')
        if animation_name == 'stun':
            animation_name = 'hit'
        elif animation_name == 'dead':
            animation_name = 'die'

        # Use the configured state settings for culling first. That preserves
        # the v7 rule that off-screen enemies do not do animation/file work.
        (
            draw_width,
            draw_height,
            draw_offset_x,
            draw_offset_y,
        ) = EnemySpriteCache.get_draw_settings(
            self.definition,
            animation_name,
        )
        visual_center_x = self.x + draw_offset_x
        visual_center_y = self.y + draw_offset_y

        if not camera.is_world_rect_visible(
            visual_center_x,
            visual_center_y,
            draw_width,
            draw_height,
        ):
            return

        resolved_animation_name = EnemySpriteCache.resolve_animation_name(
            app,
            self.definition,
            animation_name,
        )
        if resolved_animation_name != animation_name:
            # A missing action sheet falls back to Idle. Use Idle's own visual
            # settings as well, then cull again in case its size is different.
            (
                draw_width,
                draw_height,
                draw_offset_x,
                draw_offset_y,
            ) = EnemySpriteCache.get_draw_settings(
                self.definition,
                resolved_animation_name,
            )
            visual_center_x = self.x + draw_offset_x
            visual_center_y = self.y + draw_offset_y
            if not camera.is_world_rect_visible(
                visual_center_x,
                visual_center_y,
                draw_width,
                draw_height,
            ):
                return

        image = EnemySpriteCache.get_frame(
            app,
            self.definition,
            resolved_animation_name or animation_name,
            self.animation_elapsed,
            self.facing,
            force_first_frame=force_first_frame,
            loop=self.action_state in ('idle', 'walk'),
        )

        rect = camera.rect_from_world_center(
            visual_center_x,
            visual_center_y,
            draw_width,
            draw_height,
        )

        if image is None:
            pygame.draw.rect(screen, self.color, rect, border_radius=5)
            pygame.draw.rect(
                screen,
                (55, 30, 30),
                rect,
                width=2,
                border_radius=5,
            )
        else:
            screen.blit(image, rect.topleft)

        player = world.primary_player
        if not self.is_defeated and self.is_near_player(player):
            self._draw_hp_bar(screen, camera, app.timer.game_time)

    def _draw_hp_bar(
        self,
        screen: pygame.Surface,
        camera: Camera,
        now: float,
    ) -> None:
        bar_width = max(56, int(self.width))
        bar_height = 8
        screen_center_x, screen_y = camera.world_to_screen(self.x, self.y)
        y = int(screen_y - self.height * 0.5 - self.hp_bar_offset_y)
        ratio = self.hp / self.max_hp if self.max_hp > 0 else 0.0

        # UI bars are anchored to the logical monster X position, not the
        # sprite's image offset. Both HP and stun bars therefore share exactly
        # the same center line as the monster hitbox and each other.
        hp_rect = pygame.Rect(0, y, bar_width, bar_height)
        hp_rect.centerx = int(round(screen_center_x))

        pygame.draw.rect(
            screen,
            (42, 42, 48),
            hp_rect,
            border_radius=3,
        )
        pygame.draw.rect(
            screen,
            (214, 72, 72),
            (hp_rect.left, hp_rect.top, int(bar_width * ratio), bar_height),
            border_radius=3,
        )
        pygame.draw.rect(
            screen,
            (230, 230, 230),
            hp_rect,
            width=1,
            border_radius=3,
        )

        if not self.is_stunned(now):
            return

        remaining = max(0.0, self._stunned_until - now)
        total = max(self._stun_total_duration, self._EPSILON)
        stun_ratio = min(1.0, remaining / total)

        stun_rect = pygame.Rect(
            0,
            hp_rect.top - bar_height - 3,
            bar_width,
            bar_height,
        )
        stun_rect.centerx = hp_rect.centerx
        pygame.draw.rect(
            screen,
            (32, 42, 48),
            stun_rect,
            border_radius=3,
        )
        pygame.draw.rect(
            screen,
            (44, 202, 186),
            (
                stun_rect.left,
                stun_rect.top,
                int(bar_width * stun_ratio),
                bar_height,
            ),
            border_radius=3,
        )
        pygame.draw.rect(
            screen,
            (205, 242, 236),
            stun_rect,
            width=1,
            border_radius=3,
        )
