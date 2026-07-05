from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any


class JsonDataError(RuntimeError):
    """Raised when a data table is missing, malformed, or inconsistent."""


class DataRepository:
    """Loads JSON tables and validates their cross-table references."""

    TABLE_FILES = {
        'config': 'game_config.json',
        'characters': 'characters.json',
        'skills': 'skills.json',
        'items': 'items.json',
        'enemies': 'enemies.json',
        'tiles': 'tiles.json',
        'sounds': 'sounds.json',
        'stages': 'stages.json',
    }

    def __init__(self, data_directory: Path) -> None:
        self._data_directory = data_directory
        self._tables: dict[str, dict[str, Any]] = {}

    def load_all(self) -> None:
        loaded = {
            table_name: self._load_json_file(filename)
            for table_name, filename in self.TABLE_FILES.items()
        }
        self._validate(loaded)
        self._tables = loaded

    def reload_all(self) -> None:
        self.load_all()

    def config(self) -> dict[str, Any]:
        return deepcopy(self._tables['config'])

    def table(self, table_name: str) -> dict[str, Any]:
        try:
            return deepcopy(self._tables[table_name])
        except KeyError as error:
            raise JsonDataError(
                f'Unknown data table: {table_name}'
            ) from error

    def record(self, table_name: str, record_id: str) -> dict[str, Any]:
        try:
            records = self._tables[table_name]['records']
        except KeyError as error:
            raise JsonDataError(
                f'Unknown data table: {table_name}'
            ) from error

        try:
            return deepcopy(records[record_id])
        except KeyError as error:
            raise JsonDataError(
                f"'{record_id}' does not exist in "
                f"{self.TABLE_FILES.get(table_name, table_name)}"
            ) from error

    def records(self, table_name: str) -> dict[str, dict[str, Any]]:
        try:
            return deepcopy(self._tables[table_name]['records'])
        except KeyError as error:
            raise JsonDataError(
                f'Unknown record table: {table_name}'
            ) from error

    def _load_json_file(self, filename: str) -> dict[str, Any]:
        path = self._data_directory / filename

        try:
            with path.open('r', encoding='utf-8') as file:
                data = json.load(file)
        except FileNotFoundError as error:
            raise JsonDataError(
                f'Data file not found: {path}'
            ) from error
        except json.JSONDecodeError as error:
            raise JsonDataError(
                f'JSON syntax error in {path.name}: '
                f'line {error.lineno}, column {error.colno}'
            ) from error

        if not isinstance(data, dict):
            raise JsonDataError(
                f'{path.name} must have an object {{ }} at its root.'
            )

        if data.get('schema_version') != 1:
            raise JsonDataError(
                f'{path.name} must declare schema_version: 1.'
            )

        return data

    def _validate(self, tables: dict[str, dict[str, Any]]) -> None:
        for name in (
            'characters',
            'skills',
            'items',
            'enemies',
            'tiles',
            'sounds',
            'stages',
        ):
            records = tables[name].get('records')
            if not isinstance(records, dict) or not records:
                raise JsonDataError(
                    f'{self.TABLE_FILES[name]} needs a non-empty records object.'
                )

        self._validate_config(tables['config'])
        self._validate_characters(tables)
        self._validate_skills(tables)
        self._validate_items(tables)
        self._validate_enemies(tables)
        self._validate_tiles(tables)
        self._validate_sounds(tables)
        self._validate_stages(tables)

    def _validate_config(self, config: dict[str, Any]) -> None:
        self._require_keys(
            config,
            'game_config.json',
            'window',
            'runtime',
            'party',
            'enemy_shared',
        )
        self._require_keys(
            config['window'],
            'game_config.json.window',
            'width',
            'height',
            'title',
            'background_color',
        )
        self._require_keys(
            config['runtime'],
            'game_config.json.runtime',
            'target_fps',
            'max_delta_seconds',
        )
        self._require_keys(
            config['party'],
            'game_config.json.party',
            'max_selectable_characters',
        )
        self._require_keys(
            config['enemy_shared'],
            'game_config.json.enemy_shared',
            'hp_show_distance',
            'contact_cooldown_seconds',
            'hit_invulnerability_seconds',
            'near_ai_horizontal_range',
            'far_ai_interval_seconds',
            'patrol',
            'attack_charge',
        )
        enemy_shared_patrol = config['enemy_shared']['patrol']
        self._require_keys(
            enemy_shared_patrol,
            'game_config.json.enemy_shared.patrol',
            'logic_tick_seconds',
            'wander_pressure_per_tick',
            'wander_pressure_cap',
            'reverse_probability_after_idle',
            'idle_probability_steps',
        )
        enemy_shared_attack_charge = config['enemy_shared']['attack_charge']
        self._require_keys(
            enemy_shared_attack_charge,
            'game_config.json.enemy_shared.attack_charge',
            'logic_tick_seconds',
            'charge_per_tick',
            'charge_required',
        )

        for key in (
            'hp_show_distance',
            'contact_cooldown_seconds',
            'hit_invulnerability_seconds',
            'near_ai_horizontal_range',
            'far_ai_interval_seconds',
        ):
            value = config['enemy_shared'][key]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise JsonDataError(
                    f'game_config.json.enemy_shared.{key} must be a number.'
                )
            if float(value) < 0.0:
                raise JsonDataError(
                    f'game_config.json.enemy_shared.{key} cannot be negative.'
                )

        far_ai_interval = config['enemy_shared']['far_ai_interval_seconds']
        if float(far_ai_interval) <= 0.0:
            raise JsonDataError(
                'game_config.json.enemy_shared.far_ai_interval_seconds '
                'must be greater than zero.'
            )

        for key in (
            'logic_tick_seconds',
            'wander_pressure_per_tick',
            'wander_pressure_cap',
        ):
            value = enemy_shared_patrol[key]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise JsonDataError(
                    f'game_config.json.enemy_shared.patrol.{key} must be a number.'
                )
            if float(value) <= 0.0:
                raise JsonDataError(
                    f'game_config.json.enemy_shared.patrol.{key} must be greater than zero.'
                )

        for key in (
            'logic_tick_seconds',
            'charge_per_tick',
            'charge_required',
        ):
            value = enemy_shared_attack_charge[key]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise JsonDataError(
                    'game_config.json.enemy_shared.attack_charge.'
                    f'{key} must be a number.'
                )
            if float(value) <= 0.0:
                raise JsonDataError(
                    'game_config.json.enemy_shared.attack_charge.'
                    f'{key} must be greater than zero.'
                )

        reverse_probability = enemy_shared_patrol['reverse_probability_after_idle']
        if (
            isinstance(reverse_probability, bool)
            or not isinstance(reverse_probability, (int, float))
            or not 0.0 <= float(reverse_probability) <= 1.0
        ):
            raise JsonDataError(
                'game_config.json.enemy_shared.patrol.'
                'reverse_probability_after_idle must be between 0 and 1.'
            )

        probability_steps = enemy_shared_patrol['idle_probability_steps']
        if not isinstance(probability_steps, list) or not probability_steps:
            raise JsonDataError(
                'game_config.json.enemy_shared.patrol.idle_probability_steps '
                'must be a non-empty list.'
            )

        previous_minimum = -1.0
        for index, step in enumerate(probability_steps):
            label = (
                'game_config.json.enemy_shared.patrol.'
                f'idle_probability_steps[{index}]'
            )
            if not isinstance(step, dict):
                raise JsonDataError(f'{label} must be an object.')
            self._require_keys(
                step,
                label,
                'minimum_pressure',
                'idle_probability',
            )
            minimum = step['minimum_pressure']
            probability = step['idle_probability']
            if (
                isinstance(minimum, bool)
                or not isinstance(minimum, (int, float))
                or float(minimum) <= 0.0
            ):
                raise JsonDataError(
                    f'{label}.minimum_pressure must be a number greater than zero.'
                )
            if (
                isinstance(probability, bool)
                or not isinstance(probability, (int, float))
                or not 0.0 <= float(probability) <= 1.0
            ):
                raise JsonDataError(
                    f'{label}.idle_probability must be between 0 and 1.'
                )
            if float(minimum) <= previous_minimum:
                raise JsonDataError(
                    f'{label}.minimum_pressure must be strictly increasing.'
                )
            previous_minimum = float(minimum)

        if previous_minimum > float(enemy_shared_patrol['wander_pressure_cap']):
            raise JsonDataError(
                'game_config.json.enemy_shared.patrol idle probability steps '
                'cannot start above the pressure cap.'
            )

        if int(config['party']['max_selectable_characters']) != 4:
            raise JsonDataError(
                'game_config.json.party.max_selectable_characters must be 4.'
            )

    def _validate_characters(
        self,
        tables: dict[str, dict[str, Any]],
    ) -> None:
        character_table = tables['characters']
        records = character_table['records']
        if len(records) > 4:
            raise JsonDataError(
                'characters.json supports at most four character records.'
            )

        self._require_keys(
            character_table,
            'characters.json',
            'shared_settings',
        )
        shared_settings = character_table['shared_settings']
        self._require_keys(
            shared_settings,
            'characters.json.shared_settings',
            'collider',
            'combat',
            'movement',
            'respawn',
            'party',
            'visual_defaults',
        )
        self._require_keys(
            shared_settings['collider'],
            'characters.json.shared_settings.collider',
            'width',
            'height',
        )
        self._require_keys(
            shared_settings['visual_defaults'],
            'characters.json.shared_settings.visual_defaults',
            'draw_offset_x',
            'draw_offset_y',
        )
        self._require_keys(
            shared_settings['combat'],
            'characters.json.shared_settings.combat',
            'contact_invulnerability_seconds',
        )
        self._require_keys(
            shared_settings['movement'],
            'characters.json.shared_settings.movement',
            'gravity',
            'jump_speed',
            'max_fall_speed',
            'dash_speed_multiplier',
            'dash_duration_seconds',
            'dash_cooldown_seconds',
        )
        self._require_keys(
            shared_settings['respawn'],
            'characters.json.shared_settings.respawn',
            'wait_seconds',
            'experience_loss_on_hp_zero_death',
            'pit_death_depth_below_world_bottom',
        )
        self._require_keys(
            shared_settings['party'],
            'characters.json.shared_settings.party',
            'max_hp',
            'initial_hp',
            'initial_experience',
            'initial_level',
            'initial_enhancement_level',
            'starting_items',
        )

        for key in ('width', 'height'):
            if int(shared_settings['collider'][key]) <= 0:
                raise JsonDataError(
                    'characters.json.shared_settings.collider.'
                    f'{key} must be greater than zero.'
                )

        for key in ('draw_offset_x', 'draw_offset_y'):
            value = shared_settings['visual_defaults'][key]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise JsonDataError(
                    'characters.json.shared_settings.visual_defaults.'
                    f'{key} must be a number.'
                )

        shared_number_keys = (
            ('combat', 'contact_invulnerability_seconds'),
            ('movement', 'gravity'),
            ('movement', 'jump_speed'),
            ('movement', 'max_fall_speed'),
            ('movement', 'dash_speed_multiplier'),
            ('movement', 'dash_duration_seconds'),
            ('movement', 'dash_cooldown_seconds'),
            ('respawn', 'wait_seconds'),
            ('respawn', 'experience_loss_on_hp_zero_death'),
            ('respawn', 'pit_death_depth_below_world_bottom'),
            ('party', 'max_hp'),
            ('party', 'initial_hp'),
        )
        for section, key in shared_number_keys:
            value = shared_settings[section][key]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise JsonDataError(
                    'characters.json.shared_settings.'
                    f'{section}.{key} must be a number.'
                )
            if float(value) <= 0.0:
                raise JsonDataError(
                    'characters.json.shared_settings.'
                    f'{section}.{key} must be greater than zero.'
                )

        if int(shared_settings['party']['initial_hp']) > int(
            shared_settings['party']['max_hp']
        ):
            raise JsonDataError(
                'characters.json.shared_settings.party.initial_hp '
                'cannot exceed max_hp.'
            )

        for key in (
            'initial_experience',
            'initial_level',
            'initial_enhancement_level',
        ):
            value = shared_settings['party'][key]
            if isinstance(value, bool) or not isinstance(value, int):
                raise JsonDataError(
                    'characters.json.shared_settings.party.'
                    f'{key} must be an integer.'
                )
            minimum = 1 if key == 'initial_level' else 0
            if value < minimum:
                raise JsonDataError(
                    'characters.json.shared_settings.party.'
                    f'{key} must be at least {minimum}.'
                )

        for item_id, amount in shared_settings['party']['starting_items'].items():
            self._must_exist(
                tables,
                'items',
                str(item_id),
                'characters.json.shared_settings.party.starting_items',
            )
            if isinstance(amount, bool) or not isinstance(amount, int):
                raise JsonDataError(
                    'characters.json.shared_settings.party.starting_items.'
                    f'{item_id} must be an integer.'
                )
            if amount < 0:
                raise JsonDataError(
                    'characters.json.shared_settings.party.starting_items.'
                    f'{item_id} cannot be negative.'
                )

        ability_fields = (
            'basic_attack_id',
            'skill_s_id',
            'skill_d_id',
            'main_unique_skill_id',
            'main_ultimate_skill_id',
        )

        for record_id, record in records.items():
            label = f'characters.{record_id}'

            self._require_keys(
                record,
                label,
                'display_name',
                'stats',
                'ammo',
                'abilities',
                'reload',
                'visual',
            )
            self._require_keys(
                record['stats'],
                f'{label}.stats',
                'move_speed',
                'attack_speed_multiplier',
            )
            self._require_keys(
                record['abilities'],
                f'{label}.abilities',
                *ability_fields,
            )
            self._require_keys(
                record['visual'],
                f'{label}.visual',
                'directory',
                'draw_width',
                'draw_height',
                'animations',
            )

            self._validate_optional_visual_offsets(
                record['visual'],
                f'{label}.visual',
            )

            for key in ('draw_width', 'draw_height'):
                if int(record['visual'][key]) <= 0:
                    raise JsonDataError(
                        f'{label}.visual.{key} must be greater than zero.'
                    )

            if float(record['stats']['move_speed']) <= 0.0:
                raise JsonDataError(
                    f'{label}.stats.move_speed must be greater than zero.'
                )

            if float(record['stats']['attack_speed_multiplier']) <= 0.0:
                raise JsonDataError(
                    f'{label}.stats.attack_speed_multiplier '
                    'must be greater than zero.'
                )

            combat_rules = record.get('combat_rules', {})
            bindings = combat_rules.get('stagger_immune_bindings', ())
            known_binding_names = {
                'basic',
                'skill_s',
                'skill_d',
                'main_unique',
                'main_ultimate',
            }
            if not isinstance(bindings, list) or any(
                binding not in known_binding_names for binding in bindings
            ):
                raise JsonDataError(
                    f'{label}.combat_rules.stagger_immune_bindings must be '
                    'a list of known ability binding names.'
                )

            allowed_basic_attack_states = combat_rules.get(
                'basic_attack_allowed_states'
            )
            if allowed_basic_attack_states is not None:
                known_action_states = {
                    'idle', 'walk', 'jump', 'fall', 'dash', 'hit',
                    'attack', 'skill', 'reload',
                }
                if (
                    not isinstance(allowed_basic_attack_states, list)
                    or not allowed_basic_attack_states
                    or any(
                        state not in known_action_states
                        for state in allowed_basic_attack_states
                    )
                ):
                    raise JsonDataError(
                        f'{label}.combat_rules.basic_attack_allowed_states '
                        'must be a non-empty list of valid action states.'
                    )

            for ammo_type, amount in record['ammo'].items():
                if not str(ammo_type).strip():
                    raise JsonDataError(
                        f'{label}.ammo contains an empty ammo type.'
                    )
                if isinstance(amount, bool) or not isinstance(amount, int):
                    raise JsonDataError(
                        f'{label}.ammo.{ammo_type} must be an integer.'
                    )
                if amount < 0:
                    raise JsonDataError(
                        f'{label}.ammo.{ammo_type} cannot be negative.'
                    )

            reload = record['reload']
            reload_label = f'{label}.reload'
            self._require_keys(
                reload,
                reload_label,
                'mode',
                'action_duration_seconds',
                'animation_name',
            )
            if reload['mode'] not in ('standard', 'recoil_projectile'):
                raise JsonDataError(
                    f"{reload_label}.mode must be 'standard' or "
                    "'recoil_projectile'."
                )
            if float(reload['action_duration_seconds']) <= 0.0:
                raise JsonDataError(
                    f'{reload_label}.action_duration_seconds must be '
                    'greater than zero.'
                )
            if not str(reload['animation_name']).strip():
                raise JsonDataError(
                    f'{reload_label}.animation_name must be non-empty.'
                )
            if 'stagger_immunity' in reload and not isinstance(
                reload['stagger_immunity'],
                bool,
            ):
                raise JsonDataError(
                    f'{reload_label}.stagger_immunity must be a boolean.'
                )

            if reload['mode'] == 'recoil_projectile':
                self._require_keys(
                    reload,
                    reload_label,
                    'release_delay_seconds',
                    'projectile_skill_id',
                    'recoil_speed_multiplier',
                    'jump_speed_multiplier',
                )
                release_delay = float(reload['release_delay_seconds'])
                duration = float(reload['action_duration_seconds'])
                if release_delay < 0.0 or release_delay > duration:
                    raise JsonDataError(
                        f'{reload_label}.release_delay_seconds must be '
                        'between zero and action_duration_seconds.'
                    )
                if float(reload['recoil_speed_multiplier']) < 0.0:
                    raise JsonDataError(
                        f'{reload_label}.recoil_speed_multiplier cannot be '
                        'negative.'
                    )
                if float(reload['jump_speed_multiplier']) <= 0.0:
                    raise JsonDataError(
                        f'{reload_label}.jump_speed_multiplier must be '
                        'greater than zero.'
                    )
                projectile_skill_id = reload['projectile_skill_id']
                if (
                    not isinstance(projectile_skill_id, str)
                    or not projectile_skill_id.strip()
                ):
                    raise JsonDataError(
                        f'{reload_label}.projectile_skill_id must be a skill id.'
                    )
                self._must_exist(
                    tables,
                    'skills',
                    projectile_skill_id,
                    f'{reload_label}.projectile_skill_id',
                )

            animations = record['visual']['animations']
            for animation_name in ('idle', 'walk'):
                if animation_name not in animations:
                    raise JsonDataError(
                        f'{label}.visual.animations needs {animation_name}.'
                    )

            for animation_name, animation in animations.items():
                animation_label = (
                    f'{label}.visual.animations.{animation_name}'
                )
                self._require_keys(
                    animation,
                    animation_label,
                    'file_stem',
                    'fps',
                )
                if not str(animation['file_stem']).strip():
                    raise JsonDataError(
                        f'{animation_label}.file_stem must be non-empty.'
                    )
                if float(animation['fps']) <= 0.0:
                    raise JsonDataError(
                        f'{animation_label}.fps must be greater than zero.'
                    )

                self._validate_optional_visual_offsets(
                    animation,
                    animation_label,
                )

            if str(reload['animation_name']) not in animations:
                raise JsonDataError(
                    f"{reload_label}.animation_name must name an entry in "
                    'visual.animations.'
                )

            for ability_field in ability_fields:
                skill_id = record['abilities'][ability_field]
                if skill_id is None:
                    continue
                if not isinstance(skill_id, str) or not skill_id.strip():
                    raise JsonDataError(
                        f'{label}.abilities.{ability_field} must be a skill id '
                        'or null.'
                    )
                self._must_exist(
                    tables,
                    'skills',
                    skill_id,
                    f'{label}.abilities.{ability_field}',
                )

    @staticmethod
    def _validate_optional_visual_offsets(
        mapping: dict[str, Any],
        label: str,
    ) -> None:
        """Validate optional visual-only image offsets.

        Positive X is right and positive Y is up in the project's world
        coordinate system. These values never affect collider coordinates.
        """

        for key in ('draw_offset_x', 'draw_offset_y'):
            if key not in mapping:
                continue

            value = mapping[key]
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
            ):
                raise JsonDataError(
                    f'{label}.{key} must be a number when provided.'
                )


    @staticmethod
    def _validate_optional_visual_draw_sizes(
        mapping: dict[str, Any],
        label: str,
    ) -> None:
        """Validate optional render-only width/height overrides.

        The enemy collider remains ``visual.width`` / ``visual.height``.
        These optional settings affect only sprite rendering.
        """

        for key in ('draw_width', 'draw_height'):
            if key not in mapping:
                continue

            value = mapping[key]
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or float(value) <= 0.0
            ):
                raise JsonDataError(
                    f'{label}.{key} must be a number greater than zero '
                    'when provided.'
                )


    def _validate_skills(
        self,
        tables: dict[str, dict[str, Any]],
    ) -> None:
        for record_id, record in tables['skills']['records'].items():
            label = f'skills.{record_id}'
            self._require_keys(
                record,
                label,
                'display_name',
                'slot',
                'behavior_type',
                'cooldown_seconds',
                'action_state',
                'action_duration_seconds',
            )

            if float(record['cooldown_seconds']) < 0.0:
                raise JsonDataError(
                    f'{label}.cooldown_seconds cannot be negative.'
                )

            if record['action_state'] not in ('attack', 'skill'):
                raise JsonDataError(
                    f"{label}.action_state must be 'attack' or 'skill'."
                )

            if 'stagger_immunity' in record and not isinstance(
                record['stagger_immunity'],
                bool,
            ):
                raise JsonDataError(
                    f'{label}.stagger_immunity must be a boolean when provided.'
                )

            if float(record['action_duration_seconds']) < 0.0:
                raise JsonDataError(
                    f'{label}.action_duration_seconds cannot be negative.'
                )

            if 'attack_interval_seconds' in record:
                if float(record['attack_interval_seconds']) <= 0.0:
                    raise JsonDataError(
                        f'{label}.attack_interval_seconds '
                        'must be greater than zero.'
                    )

            if str(record['behavior_type']).startswith('projectile'):
                self._require_keys(record, label, 'projectile')
                self._require_keys(
                    record['projectile'],
                    f'{label}.projectile',
                    'damage',
                    'speed',
                    'lifetime_seconds',
                )

    def _validate_items(
        self,
        tables: dict[str, dict[str, Any]],
    ) -> None:
        for record_id, record in tables['items']['records'].items():
            self._require_keys(
                record,
                f'items.{record_id}',
                'display_name',
                'item_type',
                'max_stack',
                'effect',
                'visual',
            )

    def _validate_enemies(
        self,
        tables: dict[str, dict[str, Any]],
    ) -> None:
        """Validate the explicit patrol / detection / pursuit monster schema."""

        for record_id, record in tables['enemies']['records'].items():
            label = f'enemies.{record_id}'
            self._require_keys(
                record,
                label,
                'display_name',
                'archetype',
                'stats',
                'ai',
                'combat',
                'respawn',
                'ui',
                'rewards',
                'visual',
            )
            self._require_keys(
                record['stats'],
                f'{label}.stats',
                'max_hp',
                'move_speed',
                'fortitude',
                'contact_damage',
            )
            self._require_keys(
                record['ai'],
                f'{label}.ai',
                'temperament',
                'patrol',
                'detection_range_tiles',
                'pursuit',
            )
            self._require_keys(
                record['combat'],
                f'{label}.combat',
                'attack_range_tiles',
                'attack_skill_ids',
                'attack_selection_weights',
            )
            self._require_keys(
                record['respawn'],
                f'{label}.respawn',
                'min_seconds',
                'max_seconds',
            )
            self._require_keys(
                record['ui'],
                f'{label}.ui',
                'hp_bar_offset_y',
            )
            self._require_keys(
                record['rewards'],
                f'{label}.rewards',
                'experience_reward',
            )

            if record['ai']['temperament'] not in ('passive', 'aggressive'):
                raise JsonDataError(
                    f"{label}.ai.temperament must be 'passive' or 'aggressive'."
                )

            patrol = record['ai']['patrol']
            self._require_keys(
                patrol,
                f'{label}.ai.patrol',
                'range_tiles',
                'pause_min_seconds',
                'pause_max_seconds',
            )

            detection = record['ai']['detection_range_tiles']
            self._require_keys(
                detection,
                f'{label}.ai.detection_range_tiles',
                'horizontal',
                'vertical',
            )

            pursuit = record['ai']['pursuit']
            self._require_keys(
                pursuit,
                f'{label}.ai.pursuit',
                'anger_on_hit',
                'anger_gain_per_second_in_detection',
                'anger_decay_per_second_outside_range',
                'pursue_outside_patrol_threshold',
                'return_to_patrol_threshold',
                'max_chase_range_tiles',
            )

            attack_range = record['combat']['attack_range_tiles']
            self._require_keys(
                attack_range,
                f'{label}.combat.attack_range_tiles',
                'horizontal',
                'vertical',
            )

            numeric_values = (
                ('stats', 'max_hp'),
                ('stats', 'move_speed'),
                ('stats', 'fortitude'),
                ('stats', 'contact_damage'),
                ('ai.patrol', 'range_tiles'),
                ('ai.patrol', 'pause_min_seconds'),
                ('ai.patrol', 'pause_max_seconds'),
                ('ai.detection_range_tiles', 'horizontal'),
                ('ai.detection_range_tiles', 'vertical'),
                ('ai.pursuit', 'anger_on_hit'),
                ('ai.pursuit', 'anger_gain_per_second_in_detection'),
                ('ai.pursuit', 'anger_decay_per_second_outside_range'),
                ('ai.pursuit', 'pursue_outside_patrol_threshold'),
                ('ai.pursuit', 'return_to_patrol_threshold'),
                ('ai.pursuit', 'max_chase_range_tiles'),
                ('combat.attack_range_tiles', 'horizontal'),
                ('combat.attack_range_tiles', 'vertical'),
                ('respawn', 'min_seconds'),
                ('respawn', 'max_seconds'),
            )
            sections: dict[str, dict[str, Any]] = {
                'stats': record['stats'],
                'ai.patrol': patrol,
                'ai.detection_range_tiles': detection,
                'ai.pursuit': pursuit,
                'combat.attack_range_tiles': attack_range,
                'respawn': record['respawn'],
            }
            for section_name, key in numeric_values:
                value = sections[section_name][key]
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise JsonDataError(
                        f'{label}.{section_name}.{key} must be a number.'
                    )
                if float(value) < 0.0:
                    raise JsonDataError(
                        f'{label}.{section_name}.{key} cannot be negative.'
                    )

            if (
                float(patrol['pause_max_seconds'])
                < float(patrol['pause_min_seconds'])
            ):
                raise JsonDataError(
                    f'{label}.ai.patrol pause max must be >= min.'
                )
            if (
                float(record['respawn']['max_seconds'])
                < float(record['respawn']['min_seconds'])
            ):
                raise JsonDataError(
                    f'{label}.respawn.max_seconds must be >= min_seconds.'
                )

            if int(record['rewards']['experience_reward']) < 0:
                raise JsonDataError(
                    f'{label}.rewards.experience_reward cannot be negative.'
                )

            attack_ids = record['combat']['attack_skill_ids']
            if not isinstance(attack_ids, list):
                raise JsonDataError(
                    f'{label}.combat.attack_skill_ids must be a list.'
                )

            attack_id_set: set[str] = set()
            for skill_id in attack_ids:
                if not isinstance(skill_id, str) or not skill_id.strip():
                    raise JsonDataError(
                        f'{label}.combat.attack_skill_ids contains an invalid skill id.'
                    )
                self._must_exist(
                    tables,
                    'skills',
                    skill_id,
                    f'{label}.combat.attack_skill_ids',
                )
                attack_id_set.add(skill_id)

            weights = record['combat']['attack_selection_weights']
            if not isinstance(weights, dict):
                raise JsonDataError(
                    f'{label}.combat.attack_selection_weights must be an object.'
                )

            for skill_id, weight in weights.items():
                if skill_id not in attack_id_set:
                    raise JsonDataError(
                        f'{label}.combat.attack_selection_weights refers to '
                        f'non-equipped skill: {skill_id}'
                    )
                if isinstance(weight, bool) or not isinstance(weight, (int, float)):
                    raise JsonDataError(
                        f'{label}.combat.attack_selection_weights.{skill_id} '
                        'must be a number.'
                    )
                if float(weight) < 0.0:
                    raise JsonDataError(
                        f'{label}.combat.attack_selection_weights.{skill_id} '
                        'cannot be negative.'
                    )

            visual = record['visual']
            self._require_keys(
                visual,
                f'{label}.visual',
                'width',
                'height',
                'placeholder_color',
            )
            for key in ('width', 'height'):
                if int(visual[key]) <= 0:
                    raise JsonDataError(
                        f'{label}.visual.{key} must be greater than zero.'
                    )

            self._validate_optional_visual_offsets(
                visual,
                f'{label}.visual',
            )
            self._validate_optional_visual_draw_sizes(
                visual,
                f'{label}.visual',
            )

            # Animated enemy art is optional while assets are being prepared.
            if 'animations' in visual:
                self._require_keys(
                    visual,
                    f'{label}.visual',
                    'directory',
                    'draw_width',
                    'draw_height',
                )
                if not isinstance(visual['animations'], dict):
                    raise JsonDataError(
                        f'{label}.visual.animations must be an object.'
                    )
                for animation_name, animation in visual['animations'].items():
                    animation_label = (
                        f'{label}.visual.animations.{animation_name}'
                    )
                    self._require_keys(
                        animation,
                        animation_label,
                        'file_stem',
                        'fps',
                    )
                    if not str(animation['file_stem']).strip():
                        raise JsonDataError(
                            f'{animation_label}.file_stem must be non-empty.'
                        )
                    if float(animation['fps']) <= 0.0:
                        raise JsonDataError(
                            f'{animation_label}.fps must be greater than zero.'
                        )
                    self._validate_optional_visual_offsets(
                        animation,
                        animation_label,
                    )
                    self._validate_optional_visual_draw_sizes(
                        animation,
                        animation_label,
                    )

    def _validate_tiles(
        self,
        tables: dict[str, dict[str, Any]],
    ) -> None:
        tile_table = tables['tiles']
        self._require_keys(
            tile_table,
            'tiles.json',
            'tile_size',
            'block_directory',
        )

        if (
            not isinstance(tile_table['tile_size'], int)
            or tile_table['tile_size'] <= 0
        ):
            raise JsonDataError(
                'tiles.json.tile_size must be a positive integer.'
            )

        if (
            not isinstance(tile_table['block_directory'], str)
            or not tile_table['block_directory'].strip()
        ):
            raise JsonDataError(
                'tiles.json.block_directory must be a non-empty string.'
            )

        for record_id, record in tile_table['records'].items():
            label = f'tiles.{record_id}'
            self._require_keys(
                record,
                label,
                'display_name',
                'collision_mode',
            )

            if record['collision_mode'] not in ('solid', 'one_way'):
                raise JsonDataError(
                    f"{label}.collision_mode must be "
                    "'solid' or 'one_way'."
                )

    def _validate_sounds(
        self,
        tables: dict[str, dict[str, Any]],
    ) -> None:
        for record_id, record in tables['sounds']['records'].items():
            label = f'sounds.{record_id}'
            self._require_keys(
                record,
                label,
                'display_name',
                'category',
                'path',
                'volume',
            )

            if record['category'] not in ('effect', 'voice', 'bgm'):
                raise JsonDataError(
                    f"{label}.category must be 'effect', 'voice', or 'bgm'."
                )

            volume = float(record['volume'])
            if volume < 0.0 or volume > 1.0:
                raise JsonDataError(
                    f'{label}.volume must be between 0.0 and 1.0.'
                )

    def _validate_stages(
        self,
        tables: dict[str, dict[str, Any]],
    ) -> None:
        for record_id, record in tables['stages']['records'].items():
            label = f'stages.{record_id}'
            self._require_keys(
                record,
                label,
                'display_name',
                'world_bounds',
                'player_spawn',
                'terrain_regions',
                'enemy_spawns',
                'item_spawns',
                'portal',
            )
            self._require_keys(
                record['world_bounds'],
                f'{label}.world_bounds',
                'left',
                'bottom',
                'right',
                'top',
            )

            for region_index, region in enumerate(record['terrain_regions']):
                region_label = f'{label}.terrain_regions[{region_index}]'
                self._require_keys(
                    region,
                    region_label,
                    'kind',
                    'block',
                    'col',
                    'row',
                    'cols',
                    'rows',
                )

                self._must_exist(
                    tables,
                    'tiles',
                    str(region['kind']),
                    region_label,
                )

                if (
                    not isinstance(region['block'], int)
                    or region['block'] <= 0
                ):
                    raise JsonDataError(
                        f'{region_label}.block must be a positive integer.'
                    )

                for key in ('col', 'row', 'cols', 'rows'):
                    if not isinstance(region[key], int):
                        raise JsonDataError(
                            f'{region_label}.{key} must be an integer.'
                        )

                if region['col'] < 0 or region['row'] < 0:
                    raise JsonDataError(
                        f'{region_label}.col and row cannot be negative.'
                    )

                if region['cols'] <= 0 or region['rows'] <= 0:
                    raise JsonDataError(
                        f'{region_label}.cols and rows must be greater than zero.'
                    )

            for spawn in record['enemy_spawns']:
                self._must_exist(
                    tables,
                    'enemies',
                    str(spawn['enemy_id']),
                    f'{label}.enemy_spawns',
                )

            for spawn in record['item_spawns']:
                self._must_exist(
                    tables,
                    'items',
                    str(spawn['item_id']),
                    f'{label}.item_spawns',
                )

    @staticmethod
    def _require_keys(
        mapping: dict[str, Any],
        label: str,
        *keys: str,
    ) -> None:
        missing = [key for key in keys if key not in mapping]
        if missing:
            raise JsonDataError(
                f"{label} is missing required keys: {', '.join(missing)}"
            )

    @staticmethod
    def _must_exist(
        tables: dict[str, dict[str, Any]],
        table_name: str,
        record_id: str,
        reference_label: str,
    ) -> None:
        if record_id not in tables[table_name]['records']:
            raise JsonDataError(
                f"{reference_label} refers to missing "
                f"{table_name} record: '{record_id}'"
            )
