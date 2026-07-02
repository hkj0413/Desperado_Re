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
    """One terrain-aware, data-driven monster.

    Enemy source sprites face LEFT. Each spawn begins with a random facing;
    right-facing monsters use the precomputed horizontal flip.

    The AI deliberately does not have jump/fall movement. Every walk attempt
    first checks for a continuous flat surface at the spawn height and checks
    for a solid wall. A monster therefore stops instead of walking into a pit,
    falling into it, or passing through a wall.
    """

    _EPSILON = 0.01

    # Re: has terrain-aware movement, so an AI decision can be much more
    # expensive than a plain position update. Close enemies remain fully
    # responsive, while distant enemies accumulate time and make the same
    # decisions in larger, safe intervals. The next walking step is still
    # terrain-validated before movement.
    _FULL_AI_MIN_HORIZONTAL_RANGE = 800.0
    _FULL_AI_MIN_VERTICAL_RANGE = 360.0
    _REDUCED_AI_INTERVAL_SECONDS = 0.10
    _DORMANT_AI_INTERVAL_SECONDS = 0.25

    def __init__(
        self,
        enemy_id: str,
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

        self.contact_damage = max(0, int(stats.get('contact_damage', 0)))
        self.contact_cooldown_seconds = max(
            0.0,
            float(stats.get('contact_cooldown_seconds', 0.0)),
        )
        self.hit_invulnerability_seconds = max(
            0.0,
            float(stats.get('hit_invulnerability_seconds', 0.0)),
        )
        self._contact_ready_at = 0.0

        ui = definition['ui']
        self.hp_show_distance = float(ui['hp_show_distance'])
        self.hp_bar_offset_y = int(ui.get('hp_bar_offset_y', 12))

        ai = definition['ai']
        patrol = ai['patrol']
        detection = ai['detection_range_tiles']
        pursuit = ai['pursuit']

        self.temperament = str(ai['temperament'])
        self.patrol_range_tiles = max(0.0, float(patrol['range_tiles']))
        self._patrol_decision_min = max(
            0.0,
            float(patrol['decision_interval_min_seconds']),
        )
        self._patrol_decision_max = max(
            self._patrol_decision_min,
            float(patrol['decision_interval_max_seconds']),
        )
        self._patrol_pause_min = max(
            0.0,
            float(patrol['pause_min_seconds']),
        )
        self._patrol_pause_max = max(
            self._patrol_pause_min,
            float(patrol['pause_max_seconds']),
        )
        self._patrol_weights = {
            'continue': max(
                0.0,
                float(patrol['decision_weights'].get('continue', 0.0)),
            ),
            'turn': max(
                0.0,
                float(patrol['decision_weights'].get('turn', 0.0)),
            ),
            'pause': max(
                0.0,
                float(patrol['decision_weights'].get('pause', 0.0)),
            ),
        }

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
        self._surface_initialized = False
        self._tile_size = 40.0

        # Enemy source art faces LEFT; every spawn randomly faces either way.
        self.facing = random.choice((-1, 1))
        self._patrol_direction = self.facing
        self._next_patrol_decision_at = 0.0
        self._patrol_pause_until = 0.0

        self.anger = 0.0
        self._pursuit_committed = False
        self._blocked_chase = False

        self.action_state = 'idle'
        self.animation_elapsed = 0.0
        self._hit_until = 0.0
        self._stunned_until = 0.0
        self._stun_total_duration = 0.0
        self._attack_locked_until = 0.0
        self._skill_ready_at: dict[str, float] = {}
        self._respawn_ready_at = 0.0

        self._experience_claimed = False

        # Time accumulated while this enemy is outside the player's immediate
        # activity area. It is consumed by the same AI routine, so state rules
        # and movement safety stay identical; only the decision frequency drops.
        self._ai_elapsed = 0.0

        # Full route checks are intentionally cached for a short interval.
        # Actual movement still validates the next step every frame, so this
        # cache can never make an enemy walk through a wall or a pit.
        self._cached_path_is_walkable = False
        self._cached_path_target_x: float | None = None
        self._cached_path_surface_top: float | None = None
        self._next_path_check_at = 0.0

        # These ranges are derived from immutable enemy data and the stage tile
        # size. Cache them instead of rebuilding several max() expressions for
        # every nearby enemy every frame.
        self._ai_range_tile_size: float | None = None
        self._immediate_ai_horizontal_range = 0.0
        self._immediate_ai_vertical_range = 0.0
        self._reduced_ai_horizontal_range = 0.0
        self._reduced_ai_vertical_range = 0.0

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
            self._begin_death(now)
            return True

        self._hit_until = now + self.hit_invulnerability_seconds
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
        return dx * dx + dy * dy <= self.hp_show_distance ** 2

    def draw_debug_ranges(
        self,
        screen: pygame.Surface,
        camera: Camera,
    ) -> None:
        """Debug order is green detect -> orange attack -> World red AABB."""

        self._draw_debug_rectangle(
            screen,
            camera,
            self.detect_tiles_x * self._tile_size,
            self.detect_tiles_y * self._tile_size,
            (42, 220, 82),
        )
        self._draw_debug_rectangle(
            screen,
            camera,
            self.attack_tiles_x * self._tile_size,
            self.attack_tiles_y * self._tile_size,
            (255, 157, 42),
        )

    def _draw_debug_rectangle(
        self,
        screen: pygame.Surface,
        camera: Camera,
        half_width: float,
        half_height: float,
        color: tuple[int, int, int],
    ) -> None:
        if half_width <= 0.0 or half_height <= 0.0:
            return

        width = half_width * 2.0
        height = half_height * 2.0
        if not camera.is_world_rect_visible(self.x, self.y, width, height):
            return

        rect = camera.rect_from_world_center(
            self.x,
            self.y,
            width,
            height,
        )
        pygame.draw.rect(screen, color, rect, width=2)

    def update(
        self,
        delta_seconds: float,
        world: World,
        app: GameApp,
    ) -> None:
        """Advance this enemy at a distance-appropriate AI cadence.

        Nearby enemies still execute the complete routine every frame. Enemies
        outside the immediate interaction area collect ``delta_seconds`` and
        execute that same routine at 0.10 or 0.25 second intervals. This keeps
        their real movement speed correct by using the accumulated elapsed time
        while avoiding repeated detection, route, patrol, and attack decisions
        for actors that cannot currently affect the player.
        """

        now = app.timer.game_time
        self._tile_size = world.terrain_tile_size
        self._refresh_ai_activity_ranges()
        self._initialize_surface(world)

        player = world.first_with_group('player')
        interval = self._ai_interval_seconds(player)
        if interval <= self._EPSILON:
            self._ai_elapsed = 0.0
            self._update_ai(delta_seconds, world, app, now, player)
            return

        self._ai_elapsed += delta_seconds
        if self._ai_elapsed + self._EPSILON < interval:
            return

        elapsed = self._ai_elapsed
        self._ai_elapsed = 0.0
        self._update_ai(elapsed, world, app, now, player)

    def _ai_interval_seconds(self, player: Player | None) -> float:
        """Return the safe AI decision interval for the current player distance.

        The immediate range includes all enemy interaction ranges plus a margin,
        so enemies that can be seen or can realistically react remain frame
        perfect. The broader band is deliberately conservative: it covers an
        approaching player before the enemy can enter combat range.
        """

        if player is None:
            return self._DORMANT_AI_INTERVAL_SECONDS

        horizontal_distance = abs(player.x - self.x)
        vertical_distance = abs(player.y - self.y)
        if (
            horizontal_distance <= self._immediate_ai_horizontal_range
            and vertical_distance <= self._immediate_ai_vertical_range
        ):
            return 0.0

        if (
            horizontal_distance <= self._reduced_ai_horizontal_range
            and vertical_distance <= self._reduced_ai_vertical_range
        ):
            return self._REDUCED_AI_INTERVAL_SECONDS

        return self._DORMANT_AI_INTERVAL_SECONDS

    def _refresh_ai_activity_ranges(self) -> None:
        if self._ai_range_tile_size == self._tile_size:
            return

        tile_margin = self._tile_size * 4.0
        self._immediate_ai_horizontal_range = max(
            self._FULL_AI_MIN_HORIZONTAL_RANGE,
            self.hp_show_distance + tile_margin,
            self.detect_tiles_x * self._tile_size + tile_margin,
            self.attack_tiles_x * self._tile_size + tile_margin,
            self._max_chase_range_pixels + tile_margin,
        )
        self._immediate_ai_vertical_range = max(
            self._FULL_AI_MIN_VERTICAL_RANGE,
            self.detect_tiles_y * self._tile_size + tile_margin,
            self.attack_tiles_y * self._tile_size + tile_margin,
        )
        self._reduced_ai_horizontal_range = (
            self._immediate_ai_horizontal_range + self._tile_size * 16.0
        )
        self._reduced_ai_vertical_range = (
            self._immediate_ai_vertical_range + self._tile_size * 8.0
        )
        self._ai_range_tile_size = self._tile_size

    def _update_ai(
        self,
        delta_seconds: float,
        world: World,
        app: GameApp,
        now: float,
        player: Player | None,
    ) -> None:
        if self.is_defeated:
            self._update_respawn(now)
            return

        if self.is_stunned(now):
            self._set_action('stun')
            return

        self._stun_total_duration = 0.0

        if self.action_state == 'hit':
            if now < self._hit_until:
                return
            self._set_action('idle', restart_animation=True)

        if self.action_state == 'attack':
            if now < self._attack_locked_until:
                self.animation_elapsed += delta_seconds
                return
            self._set_action('idle', restart_animation=True)

        if not self.can_target_player(player):
            self._decay_anger(delta_seconds)
            self._return_or_patrol(delta_seconds, world, now)
            return

        assert player is not None
        in_detection = self._is_player_in_detection(player)
        in_home_patrol_band = (
            abs(player.x - self.spawn_x)
            <= self._patrol_range_pixels + self._EPSILON
        )
        same_flat_level = (
            abs(player.bottom - self._surface_top)
            <= self._tile_size * 0.25
        )

        if self.temperament == 'aggressive' and in_detection:
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
            # Passive monsters chase within their home patrol band after being
            # hit once. They may leave that band only after anger passes the
            # configured threshold.
            chase_base_allowed = self.anger > 0.0 and in_home_patrol_band

        if (
            self._pursuit_committed
            and abs(player.x - self.spawn_x)
            <= self._max_chase_range_pixels
        ):
            chase_base_allowed = True

        path_is_walkable = (
            same_flat_level
            and self._get_cached_path_is_walkable(player.x, world, now)
        )

        if not in_detection and self.temperament == 'aggressive':
            self._decay_anger(delta_seconds)
        elif self.temperament == 'passive' and not in_home_patrol_band:
            self._decay_anger(delta_seconds)

        if (
            chase_base_allowed
            and path_is_walkable
            and self.anger >= self.return_to_patrol_threshold
        ):
            self._blocked_chase = False

            if self._can_start_attack(
                player,
                now,
                path_is_walkable=path_is_walkable,
            ):
                self._start_attack(now, world, app)
                return

            moved = self._move_toward_x(
                player.x,
                delta_seconds,
                world,
                minimum_x=(
                    self.spawn_x - self._max_chase_range_pixels
                ),
                maximum_x=(
                    self.spawn_x + self._max_chase_range_pixels
                ),
            )
            if not moved:
                self._blocked_chase = True
                self._decay_anger(delta_seconds)
                self._set_action('idle')
            return

        # A gap or wall means do not try to force a route. Wait in place while
        # anger drains; after enough decay the normal return path takes over.
        if chase_base_allowed and not path_is_walkable:
            self._blocked_chase = True
            self._decay_anger(delta_seconds)
            self._set_action('idle')
            return

        if self.anger <= self.return_to_patrol_threshold:
            self._pursuit_committed = False
            self._blocked_chase = False

        self._return_or_patrol(delta_seconds, world, now)

    @property
    def _patrol_range_pixels(self) -> float:
        return self.patrol_range_tiles * self._tile_size

    @property
    def _max_chase_range_pixels(self) -> float:
        return self.max_chase_range_tiles * self._tile_size

    def _initialize_surface(
        self,
        world: World,
    ) -> None:
        if self._surface_initialized:
            return

        support_top = self._find_support_top(self.x, world)
        if support_top is not None:
            self._surface_top = support_top
            self.y = support_top + self.height * 0.5

        self._surface_initialized = True

    def _is_player_in_detection(self, player: Player) -> bool:
        return (
            abs(player.x - self.x)
            <= self.detect_tiles_x * self._tile_size
            and abs(player.y - self.y)
            <= self.detect_tiles_y * self._tile_size
        )

    def _is_player_in_attack_range(self, player: Player) -> bool:
        return (
            abs(player.x - self.x)
            <= self.attack_tiles_x * self._tile_size
            and abs(player.y - self.y)
            <= self.attack_tiles_y * self._tile_size
        )

    def _can_start_attack(
        self,
        player: Player,
        now: float,
        *,
        path_is_walkable: bool,
    ) -> bool:
        if not self.attack_skill_ids:
            return False

        if not self._is_player_in_attack_range(player):
            return False

        # Passive monsters with attack data are allowed to attack only after
        # they have been angered. Aggressive monsters use their normal pursue
        # state.
        if (
            self.temperament == 'passive'
            and self.anger < self.return_to_patrol_threshold
        ):
            return False

        if not path_is_walkable:
            return False

        return any(
            now >= self._skill_ready_at.get(skill_id, 0.0)
            for skill_id in self.attack_skill_ids
        )

    def _start_attack(
        self,
        now: float,
        world: World,
        app: GameApp,
    ) -> None:
        skill_id = self._choose_attack_skill(now)
        if skill_id is None:
            return

        skill = app.data.record('skills', skill_id)
        cooldown = max(0.0, float(skill.get('cooldown_seconds', 0.0)))
        duration = max(
            0.0,
            float(skill.get('action_duration_seconds', 0.0)),
        )

        self._skill_ready_at[skill_id] = now + cooldown
        self._attack_locked_until = now + duration
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
        world: World,
        now: float,
    ) -> None:
        home_distance = self.spawn_x - self.x
        if abs(home_distance) > self._tile_size * 0.1:
            moved = self._move_toward_x(
                self.spawn_x,
                delta_seconds,
                world,
                minimum_x=(
                    self.spawn_x - self._patrol_range_pixels
                ),
                maximum_x=(
                    self.spawn_x + self._patrol_range_pixels
                ),
            )
            if not moved:
                self._set_action('idle')
            return

        self._update_patrol(delta_seconds, world, now)

    def _update_patrol(
        self,
        delta_seconds: float,
        world: World,
        now: float,
    ) -> None:
        if now < self._patrol_pause_until:
            self._set_action('idle')
            return

        if now >= self._next_patrol_decision_at:
            self._choose_patrol_action(now)

        minimum_x = self.spawn_x - self._patrol_range_pixels
        maximum_x = self.spawn_x + self._patrol_range_pixels

        moved = self._move_toward_x(
            self.x + self._patrol_direction,
            delta_seconds,
            world,
            minimum_x=minimum_x,
            maximum_x=maximum_x,
        )

        if moved:
            return

        # At a patrol edge / wall / pit, reverse or pause. This is intentionally
        # different from chase behavior, which waits in place at an obstacle.
        self._patrol_direction *= -1
        self.facing = self._patrol_direction
        self._patrol_pause_until = now + random.uniform(
            self._patrol_pause_min,
            self._patrol_pause_max,
        )
        self._set_action('idle')

    def _choose_patrol_action(self, now: float) -> None:
        choices = ('continue', 'turn', 'pause')
        weights = [self._patrol_weights[name] for name in choices]

        if any(weight > 0.0 for weight in weights):
            choice = random.choices(choices, weights=weights, k=1)[0]
        else:
            choice = 'continue'

        if choice == 'turn':
            self._patrol_direction *= -1
            self.facing = self._patrol_direction

        elif choice == 'pause':
            self._patrol_pause_until = now + random.uniform(
                self._patrol_pause_min,
                self._patrol_pause_max,
            )

        self._next_patrol_decision_at = now + random.uniform(
            self._patrol_decision_min,
            self._patrol_decision_max,
        )

    def _move_toward_x(
        self,
        target_x: float,
        delta_seconds: float,
        world: World,
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

        movement = direction * self.move_speed * delta_seconds
        candidate_x = self.x + movement
        candidate_x = min(max(candidate_x, minimum_x), maximum_x)

        if abs(candidate_x - self.x) <= self._EPSILON:
            self._set_action('idle')
            return False

        if not self._can_walk_between(self.x, candidate_x, world):
            self._set_action('idle')
            return False

        self.x = candidate_x
        self._set_action('walk')
        self.animation_elapsed += delta_seconds
        return True

    def _get_cached_path_is_walkable(
        self,
        target_x: float,
        world: World,
        now: float,
    ) -> bool:
        """Refresh a long route check only when it can affect behavior.

        Route geometry is static in this stage. The next movement step is still
        checked every frame by ``_move_toward_x``, which keeps the original
        safety rule even between cached long-range checks.
        """

        refresh_distance = max(8.0, self._tile_size * 0.25)
        target_changed = (
            self._cached_path_target_x is None
            or abs(target_x - self._cached_path_target_x)
            >= refresh_distance
        )
        surface_changed = (
            self._cached_path_surface_top is None
            or abs(self._surface_top - self._cached_path_surface_top)
            > self._EPSILON
        )

        if (
            target_changed
            or surface_changed
            or now >= self._next_path_check_at
        ):
            self._cached_path_is_walkable = (
                self._has_flat_walkable_path_to(target_x, world)
            )
            self._cached_path_target_x = target_x
            self._cached_path_surface_top = self._surface_top
            self._next_path_check_at = now + 0.10

        return self._cached_path_is_walkable

    def _has_flat_walkable_path_to(
        self,
        target_x: float,
        world: World,
    ) -> bool:
        return self._can_walk_between(self.x, target_x, world)

    def _can_walk_between(
        self,
        start_x: float,
        target_x: float,
        world: World,
    ) -> bool:
        """Require a continuous flat support and no solid wall in the segment."""

        distance = target_x - start_x
        if abs(distance) <= self._EPSILON:
            return True

        step = max(4.0, self._tile_size * 0.5)
        steps = max(1, int(abs(distance) / step) + 1)

        for index in range(1, steps + 1):
            sample_x = start_x + distance * (index / steps)

            if not self._has_full_flat_support(sample_x, world):
                return False

            if self._has_solid_wall_at(sample_x, world):
                return False

        return True

    def _has_full_flat_support(
        self,
        center_x: float,
        world: World,
    ) -> bool:
        inset = min(self.width * 0.25, self._tile_size * 0.25)
        probes = (
            center_x - self.width * 0.5 + inset,
            center_x,
            center_x + self.width * 0.5 - inset,
        )

        return all(
            self._find_support_top(probe_x, world) is not None
            for probe_x in probes
        )

    def _find_support_top(
        self,
        x: float,
        world: World,
    ) -> float | None:
        for block in world.terrain_blocks_at_x(x):
            if not (block.is_solid or block.is_one_way):
                continue

            if (
                block.left - self._EPSILON <= x
                <= block.right + self._EPSILON
                and abs(block.top - self._surface_top)
                <= self._tile_size * 0.1
            ):
                return block.top

        return None

    def _has_solid_wall_at(
        self,
        center_x: float,
        world: World,
    ) -> bool:
        target_left = center_x - self.width * 0.5
        target_right = center_x + self.width * 0.5
        target_bottom = self._surface_top
        target_top = target_bottom + self.height

        for block in world.terrain_blocks_overlapping_x(
            target_left,
            target_right,
        ):
            if not block.is_solid:
                continue

            overlaps_x = (
                target_right > block.left + self._EPSILON
                and target_left < block.right - self._EPSILON
            )
            if not overlaps_x:
                continue

            overlaps_y = (
                target_top > block.bottom + self._EPSILON
                and target_bottom < block.top - self._EPSILON
            )
            if overlaps_y:
                return True

        return False

    def _decay_anger(self, delta_seconds: float) -> None:
        self.anger = max(
            0.0,
            self.anger
            - self.anger_decay_per_second_outside_range * delta_seconds,
        )

    def _begin_death(self, now: float) -> None:
        self._respawn_ready_at = now + random.uniform(
            self._respawn_min_seconds,
            self._respawn_max_seconds,
        )
        self._contact_ready_at = float('inf')
        self._stunned_until = 0.0
        self._stun_total_duration = 0.0
        self._hit_until = 0.0
        self._cached_path_target_x = None
        self._cached_path_surface_top = None
        self._next_path_check_at = 0.0
        self._ai_elapsed = 0.0
        self._set_action('dead', restart_animation=True)

    def _update_respawn(self, now: float) -> None:
        if now < self._respawn_ready_at:
            self._set_action('dead')
            return

        self.hp = self.max_hp
        self.x = self.spawn_x
        self.y = self.spawn_y
        self._surface_top = self.bottom
        self._surface_initialized = False

        self.facing = random.choice((-1, 1))
        self._patrol_direction = self.facing
        self._next_patrol_decision_at = 0.0
        self._patrol_pause_until = 0.0

        self.anger = 0.0
        self._pursuit_committed = False
        self._blocked_chase = False

        self._hit_until = 0.0
        self._stunned_until = 0.0
        self._attack_locked_until = 0.0
        self._skill_ready_at.clear()
        self._contact_ready_at = 0.0
        self._respawn_ready_at = 0.0
        self._experience_claimed = False
        self._ai_elapsed = 0.0
        self._cached_path_target_x = None
        self._cached_path_surface_top = None
        self._next_path_check_at = 0.0
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
        visual = self.definition['visual']
        draw_width = float(visual.get('draw_width', self.width))
        draw_height = float(visual.get('draw_height', self.height))

        visual_center_x = self.x + float(visual.get('draw_offset_x', 0.0))
        visual_center_y = self.y + float(visual.get('draw_offset_y', 0.0))

        # Off-screen enemies do not need animation resolution or frame lookup.
        if not camera.is_world_rect_visible(
            visual_center_x,
            visual_center_y,
            draw_width,
            draw_height,
        ):
            return

        animation_name = self.action_state
        force_first_frame = animation_name in ('hit', 'stun')
        if animation_name == 'stun':
            animation_name = 'hit'
        elif animation_name == 'dead':
            animation_name = 'die'

        image = EnemySpriteCache.get_frame(
            app,
            self.definition,
            animation_name,
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

        player = world.first_with_group('player')
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
        screen_x, screen_y = camera.world_to_screen(self.x, self.y)
        x = int(screen_x - bar_width * 0.5)
        y = int(screen_y - self.height * 0.5 - self.hp_bar_offset_y)
        ratio = self.hp / self.max_hp if self.max_hp > 0 else 0.0

        pygame.draw.rect(
            screen,
            (42, 42, 48),
            (x, y, bar_width, bar_height),
            border_radius=3,
        )
        pygame.draw.rect(
            screen,
            (214, 72, 72),
            (x, y, int(bar_width * ratio), bar_height),
            border_radius=3,
        )
        pygame.draw.rect(
            screen,
            (230, 230, 230),
            (x, y, bar_width, bar_height),
            width=1,
            border_radius=3,
        )

        if not self.is_stunned(now):
            return

        remaining = max(0.0, self._stunned_until - now)
        total = max(self._stun_total_duration, self._EPSILON)
        stun_ratio = min(1.0, remaining / total)

        stun_y = y - bar_height - 3
        pygame.draw.rect(
            screen,
            (32, 42, 48),
            (x, stun_y, bar_width, bar_height),
            border_radius=3,
        )
        pygame.draw.rect(
            screen,
            (44, 202, 186),
            (x, stun_y, int(bar_width * stun_ratio), bar_height),
            border_radius=3,
        )
        pygame.draw.rect(
            screen,
            (205, 242, 236),
            (x, stun_y, bar_width, bar_height),
            width=1,
            border_radius=3,
        )
