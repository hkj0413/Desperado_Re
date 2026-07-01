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
        )
        self._require_keys(
            shared_settings['collider'],
            'characters.json.shared_settings.collider',
            'width',
            'height',
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

        shared_number_keys = (
            ('combat', 'contact_invulnerability_seconds'),
            ('movement', 'gravity'),
            ('movement', 'jump_speed'),
            ('movement', 'max_fall_speed'),
            ('movement', 'dash_speed_multiplier'),
            ('movement', 'dash_duration_seconds'),
            ('movement', 'dash_cooldown_seconds'),
            ('respawn', 'wait_seconds'),
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

        mirror_key = 'mirror_draw_offset_x_when_facing_left'
        if mirror_key in mapping and not isinstance(
            mapping[mirror_key],
            bool,
        ):
            raise JsonDataError(
                f'{label}.{mirror_key} must be true or false when provided.'
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
        for record_id, record in tables['enemies']['records'].items():
            label = f'enemies.{record_id}'
            self._require_keys(
                record,
                label,
                'display_name',
                'archetype',
                'stats',
                'ai',
                'ui',
                'rewards',
                'visual',
            )
            self._require_keys(
                record['stats'],
                f'{label}.stats',
                'max_hp',
                'move_speed',
                'contact_damage',
            )
            self._require_keys(
                record['ui'],
                f'{label}.ui',
                'hp_show_distance',
            )
            self._require_keys(
                record['rewards'],
                f'{label}.rewards',
                'experience_reward',
            )
            if int(record['rewards']['experience_reward']) < 0:
                raise JsonDataError(
                    f'{label}.rewards.experience_reward cannot be negative.'
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
