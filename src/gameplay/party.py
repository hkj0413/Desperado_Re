from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Literal

PartySlot = Literal['main', 'sub']
CharacterActionState = Literal[
    'idle',
    'walk',
    'attack',
    'skill',
    'reload',
    'dash',
    'jump',
    'fall',
    'hit',
    'dead',
    'respawn_wait',
]

# Movement, combat selection, and reload progress are separate axes.  The old
# Desperado character used the same idea through parallel values such as
# Character.state, Jump, Fall, Move, and Reload_SG.  Re: keeps that separation
# per character instead of using module-global flags.
CharacterLocomotionState = Literal['idle', 'walk', 'jump', 'fall', 'dash']
CharacterCombatState = Literal[0, 1, 2, 3, 4]


@dataclass
class ReloadRuntime:
    """One active reload action for the current character.

    ``release_at`` is used by recoil-projectile reloads. Standard reloads set
    it to ``None`` and simply restore the magazine when their animation/action
    time ends.
    """

    mode: str
    direction: int
    release_at: float | None
    projectile_skill_id: str | None
    recoil_speed: float
    jump_speed: float
    # Completion and visual data live here rather than in action_state so an
    # SG reload survives physical-state changes such as jump/fall/dash.
    complete_at: float
    animation_name: str
    animation_playback_speed: float
    released: bool = False


@dataclass
class CharacterRuntimeState:
    """Runtime values that stay independent for each selected character.

    Shared values are kept only in PartyManager:
    HP, experience, level, enhancement, normal inventory, item cooldowns,
    dash cooldown, respawn timing, and the party's current facing direction.
    """

    character_id: str
    ammo: dict[str, int]
    max_ammo: dict[str, int]
    cooldown_ready_at: dict[str, float] = field(default_factory=dict)

    animation_name: str = 'idle'
    animation_elapsed: float = 0.0
    animation_playback_speed: float = 1.0

    # The base value is restored after a death cancels temporary skill effects.
    base_attack_speed_multiplier: float = 1.0
    attack_speed_multiplier: float = 1.0

    # ``locomotion_state`` is physical movement only. It stays jump/fall/dash
    # even when an action sheet is visually overlaid on top of it.
    locomotion_state: CharacterLocomotionState = 'idle'

    # ``combat_state`` follows the original character-state idea:
    # 0 = basic/default, 1 = unique (X), 2 = S skill, 3 = D skill,
    # 4 = ultimate (C). Reload has its own ReloadRuntime below, because it is
    # not a combat skill and may coexist with movement/jump/fall/dash.
    combat_state: CharacterCombatState = 0

    # Kept for compatibility with HUD, action locks, hit, death, and existing
    # systems. It represents the foreground action/reaction presentation, not
    # the only source of movement truth.
    action_state: CharacterActionState = 'idle'
    action_locked_until: float = 0.0
    hit_invulnerable_until: float = 0.0
    active_action_id: str | None = None
    active_action_stagger_immune: bool = False
    # A physical state (jump/fall/dash) may own movement while a timed
    # action still owns the visible sheet. This keeps reload/attack animation
    # progress independent from the locomotion state.
    active_action_animation_name: str | None = None
    active_action_animation_playback_speed: float = 1.0

    dash_active_until: float = 0.0
    dash_direction: int = 1

    reload: ReloadRuntime | None = None

    # Reserved for later values that truly belong to this one character only.
    status: dict[str, Any] = field(default_factory=dict)


class PartyManager:
    """Owns the selected pair and every party-wide runtime value."""

    def __init__(
        self,
        *,
        main_character_id: str,
        sub_character_id: str,
        character_definitions: dict[str, dict[str, Any]],
        item_definitions: dict[str, dict[str, Any]],
        shared_settings: dict[str, Any],
    ) -> None:
        if main_character_id == sub_character_id:
            raise ValueError('Main and sub characters must be different.')

        if main_character_id not in character_definitions:
            raise KeyError(f'Missing main character: {main_character_id}')

        if sub_character_id not in character_definitions:
            raise KeyError(f'Missing sub character: {sub_character_id}')

        self._definitions = {
            main_character_id: deepcopy(character_definitions[main_character_id]),
            sub_character_id: deepcopy(character_definitions[sub_character_id]),
        }
        self._item_definitions = deepcopy(item_definitions)
        self.shared_settings = deepcopy(shared_settings)

        # Every character inherits the common visual alignment. A character may
        # still override these two numbers in its own visual block, while a
        # specific animation can add a further state-only adjustment.
        visual_defaults = self.shared_settings.get('visual_defaults', {})
        for definition in self._definitions.values():
            visual = definition['visual']
            visual.setdefault(
                'draw_offset_x',
                float(visual_defaults.get('draw_offset_x', 0.0)),
            )
            visual.setdefault(
                'draw_offset_y',
                float(visual_defaults.get('draw_offset_y', -34.0)),
            )

        self._members: dict[PartySlot, CharacterRuntimeState] = {
            'main': self._make_runtime_state(
                main_character_id,
                self._definitions[main_character_id],
            ),
            'sub': self._make_runtime_state(
                sub_character_id,
                self._definitions[sub_character_id],
            ),
        }
        self.active_slot: PartySlot = 'main'

        # Facing is intentionally party-wide. Swapping main/sub does not make
        # the newly active character turn around.
        self.shared_facing = 1

        party_settings = self.shared_settings['party']
        self.max_hp = int(party_settings['max_hp'])
        self.shared_hp = int(party_settings['initial_hp'])
        self.shared_experience = int(party_settings['initial_experience'])
        self.shared_level = int(party_settings['initial_level'])
        self.shared_enhancement_level = int(
            party_settings['initial_enhancement_level']
        )

        # Cooldowns for normal shared hotbar items are party-wide.
        self.shared_item_cooldown_ready_at: dict[str, float] = {}

        # Dash and respawn are also party-wide rules.
        self.shared_dash_ready_at = 0.0
        self.shared_respawn_ready_at = 0.0
        # ``hp_zero`` restores HP after respawn and charges experience loss.
        # ``pit`` preserves current HP and experience exactly as requested.
        self.shared_death_cause: str | None = None

        self.shared_inventory: dict[str, int] = {}
        self.hotbar_item_ids: list[str] = []
        self.selected_hotbar_index = 0
        self._add_shared_starting_items()

    @property
    def active_character_id(self) -> str:
        return self._members[self.active_slot].character_id

    @property
    def active_runtime(self) -> CharacterRuntimeState:
        return self._members[self.active_slot]

    @property
    def active_definition(self) -> dict[str, Any]:
        return self._definitions[self.active_character_id]

    @property
    def main_character_id(self) -> str:
        return self._members['main'].character_id

    @property
    def sub_character_id(self) -> str:
        return self._members['sub'].character_id

    @property
    def selected_hotbar_item_id(self) -> str | None:
        self._remove_empty_hotbar_entries()

        if not self.hotbar_item_ids:
            return None

        self.selected_hotbar_index %= len(self.hotbar_item_ids)
        return self.hotbar_item_ids[self.selected_hotbar_index]

    @property
    def respawn_wait_seconds(self) -> float:
        return float(self.shared_settings['respawn']['wait_seconds'])

    def runtime_for(self, slot: PartySlot) -> CharacterRuntimeState:
        return self._members[slot]

    def definition_for(self, slot: PartySlot) -> dict[str, Any]:
        character_id = self._members[slot].character_id
        return self._definitions[character_id]

    def swap(self) -> PartySlot:
        self.active_slot = 'sub' if self.active_slot == 'main' else 'main'
        return self.active_slot

    def apply_damage(self, amount: int) -> int:
        self.shared_hp = max(0, self.shared_hp - max(0, int(amount)))
        return self.shared_hp

    def heal(self, amount: int) -> int:
        self.shared_hp = min(
            self.max_hp,
            self.shared_hp + max(0, int(amount)),
        )
        return self.shared_hp

    def restore_full_hp(self) -> int:
        self.shared_hp = self.max_hp
        return self.shared_hp

    def lose_experience(self, amount: int) -> int:
        """Apply a death penalty without ever lowering level or going below 0."""

        self.shared_experience = max(
            0,
            self.shared_experience - max(0, int(amount)),
        )
        return self.shared_experience

    def add_experience(self, amount: int) -> int:
        """Experience belongs to the party.

        Level-up thresholds are deliberately not invented here yet. When the
        level table is added, it should update this one shared_level value.
        """

        self.shared_experience += max(0, int(amount))
        return self.shared_experience

    def set_shared_level(self, level: int) -> int:
        self.shared_level = max(1, int(level))
        return self.shared_level

    def set_shared_enhancement_level(self, level: int) -> int:
        self.shared_enhancement_level = max(0, int(level))
        return self.shared_enhancement_level

    def cancel_all_temporary_actions(self) -> None:
        """Cancel every temporary action/effect without restoring ammunition.

        Reload completion is the sole place that may refill a magazine. Death
        calls this method before Die begins, so a partly completed reload stays
        empty through respawn. Cooldowns intentionally remain spent.
        """

        for runtime in self._members.values():
            runtime.locomotion_state = 'idle'
            runtime.combat_state = 0
            runtime.action_state = 'idle'
            runtime.action_locked_until = 0.0
            runtime.hit_invulnerable_until = 0.0
            runtime.dash_active_until = 0.0
            runtime.reload = None
            runtime.active_action_id = None
            runtime.active_action_stagger_immune = False
            runtime.active_action_animation_name = None
            runtime.active_action_animation_playback_speed = 1.0
            runtime.attack_speed_multiplier = runtime.base_attack_speed_multiplier
            runtime.status.clear()
            runtime.animation_name = 'idle'
            runtime.animation_elapsed = 0.0
            runtime.animation_playback_speed = 1.0

    def begin_shared_death(self, cause: str) -> None:
        """Record death type and erase all cancellable action state.

        The active Player then assigns its visible ``dead`` state and Die sheet.
        ``cause`` is preserved until respawn so HP-zero and pit deaths follow
        different recovery rules.
        """

        if cause not in ('hp_zero', 'pit'):
            raise ValueError(f'Unknown death cause: {cause}')

        self.shared_death_cause = cause
        self.cancel_all_temporary_actions()

    def start_shared_respawn_wait(self, now: float) -> float:
        """Start one party-wide respawn countdown after the visible Die sheet."""

        self.shared_respawn_ready_at = now + self.respawn_wait_seconds

        for runtime in self._members.values():
            runtime.locomotion_state = 'idle'
            runtime.combat_state = 0
            runtime.action_state = 'respawn_wait'
            runtime.action_locked_until = float('inf')
            runtime.hit_invulnerable_until = 0.0
            runtime.dash_active_until = 0.0
            runtime.reload = None
            runtime.active_action_id = None
            runtime.active_action_stagger_immune = False
            runtime.active_action_animation_name = None
            runtime.active_action_animation_playback_speed = 1.0
            runtime.animation_name = 'idle'
            runtime.animation_elapsed = 0.0
            runtime.animation_playback_speed = 1.0

        return self.shared_respawn_ready_at

    @property
    def is_respawning(self) -> bool:
        return self.shared_respawn_ready_at > 0.0

    def set_shared_facing(self, value: int) -> int:
        self.shared_facing = 1 if value >= 0 else -1
        return self.shared_facing

    def finish_shared_respawn(self) -> None:
        """Finish respawn using the cause recorded when death began.

        HP-zero death restores all HP. Pit death deliberately preserves the
        player's current HP and never touches experience. Neither route refills
        ammunition; only a reload that reached its own completion can do that.
        """

        if self.shared_death_cause == 'hp_zero':
            self.restore_full_hp()

        self.shared_respawn_ready_at = 0.0
        self.shared_death_cause = None
        # The first stage spawn always begins facing right. Respawn restores
        # the same party-wide baseline before normal input can turn the player.
        self.shared_facing = 1

        for runtime in self._members.values():
            runtime.locomotion_state = 'idle'
            runtime.combat_state = 0
            runtime.action_state = 'idle'
            runtime.action_locked_until = 0.0
            runtime.hit_invulnerable_until = 0.0
            runtime.dash_active_until = 0.0
            runtime.reload = None
            runtime.active_action_id = None
            runtime.active_action_stagger_immune = False
            runtime.active_action_animation_name = None
            runtime.active_action_animation_playback_speed = 1.0
            runtime.attack_speed_multiplier = runtime.base_attack_speed_multiplier
            runtime.status.clear()
            runtime.animation_name = 'idle'
            runtime.animation_elapsed = 0.0
            runtime.animation_playback_speed = 1.0

    def add_shared_item(
        self,
        item_id: str,
        amount: int,
        item_definition: dict[str, Any] | None = None,
    ) -> int:
        """Add a normal item to the common inventory and hotbar."""

        item_definition = item_definition or self._item_definitions.get(item_id)
        if item_definition is None:
            raise KeyError(f'Missing item definition: {item_id}')

        maximum = int(item_definition['max_stack'])
        current = self.shared_inventory.get(item_id, 0)
        accepted = max(0, min(max(0, int(amount)), maximum - current))

        if accepted <= 0:
            return 0

        self.shared_inventory[item_id] = current + accepted
        if item_id not in self.hotbar_item_ids:
            self.hotbar_item_ids.append(item_id)

        return accepted

    def consume_shared_item(self, item_id: str, amount: int = 1) -> bool:
        """Consume a shared item and keep the hotbar cursor valid."""

        current = self.shared_inventory.get(item_id, 0)
        amount = max(0, int(amount))

        if amount <= 0 or current < amount:
            return False

        remaining = current - amount
        if remaining > 0:
            self.shared_inventory[item_id] = remaining
        else:
            self.shared_inventory.pop(item_id, None)
            if item_id in self.hotbar_item_ids:
                removed_index = self.hotbar_item_ids.index(item_id)
                self.hotbar_item_ids.remove(item_id)

                if self.hotbar_item_ids:
                    if removed_index < self.selected_hotbar_index:
                        self.selected_hotbar_index -= 1
                    self.selected_hotbar_index %= len(self.hotbar_item_ids)
                else:
                    self.selected_hotbar_index = 0

        return True

    def move_hotbar_cursor(self, direction: int) -> str | None:
        """Move the Q/E hotbar selection one slot left or right."""

        self._remove_empty_hotbar_entries()

        if not self.hotbar_item_ids:
            self.selected_hotbar_index = 0
            return None

        step = -1 if direction < 0 else 1
        self.selected_hotbar_index = (
            self.selected_hotbar_index + step
        ) % len(self.hotbar_item_ids)
        return self.selected_hotbar_item_id

    @staticmethod
    def _make_runtime_state(
        character_id: str,
        definition: dict[str, Any],
    ) -> CharacterRuntimeState:
        stats = definition['stats']
        max_ammo = {
            str(ammo_type): max(0, int(amount))
            for ammo_type, amount in definition['ammo'].items()
        }

        base_attack_speed_multiplier = max(
            0.01,
            float(stats.get('attack_speed_multiplier', 1.0)),
        )
        return CharacterRuntimeState(
            character_id=character_id,
            ammo=dict(max_ammo),
            max_ammo=max_ammo,
            base_attack_speed_multiplier=base_attack_speed_multiplier,
            attack_speed_multiplier=base_attack_speed_multiplier,
        )

    def _add_shared_starting_items(self) -> None:
        """Add the party's common starting items once, not once per member."""

        items = self.shared_settings['party']['starting_items']
        for item_id, amount in items.items():
            self.add_shared_item(
                str(item_id),
                int(amount),
                self._item_definitions.get(str(item_id)),
            )

    def _remove_empty_hotbar_entries(self) -> None:
        self.hotbar_item_ids = [
            item_id
            for item_id in self.hotbar_item_ids
            if self.shared_inventory.get(item_id, 0) > 0
        ]

        if self.hotbar_item_ids:
            self.selected_hotbar_index %= len(self.hotbar_item_ids)
        else:
            self.selected_hotbar_index = 0
