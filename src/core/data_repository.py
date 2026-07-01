from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any


class JsonDataError(RuntimeError):
    """Raised when a data table is missing, malformed, or inconsistent."""


class DataRepository:
    """Loads JSON data tables and validates cross-table references.

    Runtime entities receive copied definitions, so changing a monster's current
    HP or a player's cooldown can never mutate the loaded JSON table.
    """

    TABLE_FILES = {
        'config': 'game_config.json',
        'characters': 'characters.json',
        'skills': 'skills.json',
        'items': 'items.json',
        'enemies': 'enemies.json',
        'tiles': 'tiles.json',
        'stages': 'stages.json',
    }

    def __init__(self, data_directory: Path) -> None:
        self._data_directory = data_directory
        self._tables: dict[str, dict[str, Any]] = {}

    def load_all(self) -> None:
        loaded: dict[str, dict[str, Any]] = {}

        for table_name, filename in self.TABLE_FILES.items():
            loaded[table_name] = self._load_json_file(filename)

        self._validate(loaded)
        self._tables = loaded

    def reload_all(self) -> None:
        self.load_all()

    def config(self) -> dict[str, Any]:
        return deepcopy(self._tables['config'])

    def table(self, table_name: str) -> dict[str, Any]:
        """Return an entire data table copy."""

        try:
            return deepcopy(self._tables[table_name])
        except KeyError as error:
            raise JsonDataError(f'Unknown data table: {table_name}') from error

    def record(self, table_name: str, record_id: str) -> dict[str, Any]:
        try:
            records = self._tables[table_name]['records']
        except KeyError as error:
            raise JsonDataError(f'Unknown data table: {table_name}') from error

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
            raise JsonDataError(f'Data file not found: {path}') from error

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
            'stages',
        ):
            records = tables[name].get('records')

            if not isinstance(records, dict) or not records:
                raise JsonDataError(
                    f'{self.TABLE_FILES[name]} needs a non-empty records object.'
                )

        self._require_keys(
            tables['config'],
            'game_config.json',
            'window',
            'runtime',
        )

        self._require_keys(
            tables['config']['window'],
            'game_config.json.window',
            'width',
            'height',
            'title',
            'background_color',
        )

        self._require_keys(
            tables['config']['runtime'],
            'game_config.json.runtime',
            'target_fps',
            'max_delta_seconds',
        )

        for record_id, record in tables['characters']['records'].items():
            self._require_keys(
                record,
                f'characters.{record_id}',
                'display_name',
                'stats',
                'movement',
                'starting_loadout',
                'visual',
            )

            self._require_keys(
                record['stats'],
                f'characters.{record_id}.stats',
                'max_hp',
                'move_speed',
            )

            self._require_keys(
                record['movement'],
                f'characters.{record_id}.movement',
                'gravity',
                'jump_speed',
                'max_fall_speed',
            )

            self._require_keys(
                record['starting_loadout'],
                f'characters.{record_id}.starting_loadout',
                'skill_ids',
                'items',
            )

            for skill_id in record['starting_loadout']['skill_ids']:
                self._must_exist(
                    tables,
                    'skills',
                    skill_id,
                    f'characters.{record_id}.starting_loadout.skill_ids',
                )

        for record_id, record in tables['skills']['records'].items():
            self._require_keys(
                record,
                f'skills.{record_id}',
                'display_name',
                'slot',
                'behavior_type',
                'cooldown_seconds',
            )

            if record['behavior_type'].startswith('projectile'):
                self._require_keys(
                    record,
                    f'skills.{record_id}',
                    'projectile',
                )

                self._require_keys(
                    record['projectile'],
                    f'skills.{record_id}.projectile',
                    'damage',
                    'speed',
                    'lifetime_seconds',
                )

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

        for record_id, record in tables['enemies']['records'].items():
            self._require_keys(
                record,
                f'enemies.{record_id}',
                'display_name',
                'archetype',
                'stats',
                'ai',
                'ui',
                'visual',
            )

            self._require_keys(
                record['stats'],
                f'enemies.{record_id}.stats',
                'max_hp',
                'move_speed',
                'contact_damage',
            )

            self._require_keys(
                record['ui'],
                f'enemies.{record_id}.ui',
                'hp_show_distance',
            )

        tile_table = tables['tiles']

        self._require_keys(
            tile_table,
            'tiles.json',
            'tile_size',
            'block_directory',
        )

        tile_size = tile_table['tile_size']

        if not isinstance(tile_size, int) or tile_size <= 0:
            raise JsonDataError(
                'tiles.json.tile_size must be a positive integer.'
            )

        block_directory = tile_table['block_directory']

        if not isinstance(block_directory, str) or not block_directory.strip():
            raise JsonDataError(
                'tiles.json.block_directory must be a non-empty string.'
            )

        for record_id, record in tile_table['records'].items():
            self._require_keys(
                record,
                f'tiles.{record_id}',
                'display_name',
                'collision_mode',
            )

            if record['collision_mode'] not in ('solid', 'one_way'):
                raise JsonDataError(
                    f"tiles.{record_id}.collision_mode must be "
                    f"'solid' or 'one_way'."
                )

        for record_id, record in tables['stages']['records'].items():
            self._require_keys(
                record,
                f'stages.{record_id}',
                'display_name',
                'player_character_id',
                'world_bounds',
                'player_spawn',
                'terrain_regions',
                'enemy_spawns',
                'item_spawns',
                'portal',
            )

            self._require_keys(
                record['world_bounds'],
                f'stages.{record_id}.world_bounds',
                'left',
                'top',
                'right',
                'bottom',
            )

            self._must_exist(
                tables,
                'characters',
                record['player_character_id'],
                f'stages.{record_id}.player_character_id',
            )

            for region_index, region in enumerate(record['terrain_regions']):
                label = (
                    f'stages.{record_id}.terrain_regions[{region_index}]'
                )

                self._require_keys(
                    region,
                    label,
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
                    label,
                )

                if (
                    not isinstance(region['block'], int)
                    or region['block'] <= 0
                ):
                    raise JsonDataError(
                        f'{label}.block must be a positive integer. '
                        'Example: "block": 1'
                    )

                for key in ('col', 'row', 'cols', 'rows'):
                    if not isinstance(region[key], int):
                        raise JsonDataError(
                            f'{label}.{key} must be an integer.'
                        )

                if region['col'] < 0 or region['row'] < 0:
                    raise JsonDataError(
                        f'{label}.col and row cannot be negative.'
                    )

                if region['cols'] <= 0 or region['rows'] <= 0:
                    raise JsonDataError(
                        f'{label}.cols and rows must be greater than zero.'
                    )

            for spawn in record['enemy_spawns']:
                self._must_exist(
                    tables,
                    'enemies',
                    spawn['enemy_id'],
                    f'stages.{record_id}.enemy_spawns',
                )

            for spawn in record['item_spawns']:
                self._must_exist(
                    tables,
                    'items',
                    spawn['item_id'],
                    f'stages.{record_id}.item_spawns',
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