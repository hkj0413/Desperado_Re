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
    'dash',
    'jump',
    'fall',
    'hit',
    'dead',
    'respawn_wait',
]


@dataclass
class CharacterRuntimeState:
    """Runtime values that stay independent for each selected character.

    Shared values are kept only in PartyManager:
    HP, experience, level, enhancement, normal inventory, item cooldowns,
    dash cooldown, respawn timing, and the party's current facing direction.
    """

    character_id: str
    ammo: dict[str, int]
    cooldown_ready_at: dict[str, float] = field(default_factory=dict)

    animation_name: str = 'idle'
    animation_elapsed: float = 0.0
    animation_playback_speed: float = 1.0

    attack_speed_multiplier: float = 1.0

    action_state: CharacterActionState = 'idle'
    action_locked_until: float = 0.0
    hit_invulnerable_until: float = 0.0

    dash_active_until: float = 0.0
    dash_direction: int = 1

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

    def start_shared_respawn_wait(self, now: float) -> float:
        """Start one party-wide respawn countdown.

        Both selected members become unavailable while the countdown runs.
        Character-specific ammunition and skill cooldowns are intentionally
        preserved; only transient action / hit / dash state is reset on respawn.
        """

        self.shared_respawn_ready_at = now + self.respawn_wait_seconds

        for runtime in self._members.values():
            runtime.action_state = 'respawn_wait'
            runtime.action_locked_until = float('inf')
            runtime.hit_invulnerable_until = 0.0
            runtime.dash_active_until = 0.0
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
        """Clear only temporary state after a party-wide respawn completes."""

        self.restore_full_hp()
        self.shared_respawn_ready_at = 0.0

        for runtime in self._members.values():
            runtime.action_state = 'idle'
            runtime.action_locked_until = 0.0
            runtime.hit_invulnerable_until = 0.0
            runtime.dash_active_until = 0.0
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

        return CharacterRuntimeState(
            character_id=character_id,
            ammo=dict(definition['ammo']),
            attack_speed_multiplier=max(
                0.01,
                float(stats.get('attack_speed_multiplier', 1.0)),
            ),
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
