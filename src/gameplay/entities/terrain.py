from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import pygame

from src.gameplay.entities.base import Entity

if TYPE_CHECKING:
    from src.app import GameApp
    from src.core.camera import Camera
    from src.core.world import World


class TerrainBlock(Entity):
    """One repeated grid tile of terrain.

    Block PNGs are cached as 40 x 40 (or the current ``tile_size``) surfaces.
    Startup preloading fills the same cache used by draw(), so a visible block
    never performs disk I/O during gameplay.
    """

    _surface_cache: dict[tuple[str, int], pygame.Surface] = {}

    def __init__(
        self,
        kind: str,
        definition: dict[str, Any],
        world_left: float,
        world_bottom: float,
        tile_size: int,
        *,
        block_number: int,
        block_directory: str,
        grid_col: int,
        grid_row: int,
    ) -> None:
        super().__init__(
            x=world_left + tile_size * 0.5,
            y=world_bottom + tile_size * 0.5,
            width=float(tile_size),
            height=float(tile_size),
            layer=int(definition.get('layer', 10)),
            collision_group='terrain',
        )

        self.kind = kind
        self.collision_mode = str(definition['collision_mode'])

        self.tile_size = int(tile_size)
        self.block_number = int(block_number)
        self.grid_col = grid_col
        self.grid_row = grid_row

        self.image_path = str(
            Path(block_directory)
            / f'Block ({self.block_number}).png'
        )

    @classmethod
    def clear_cache(cls) -> None:
        cls._surface_cache.clear()

    @classmethod
    def preload_all_stage_blocks(cls, app: GameApp) -> int:
        """Preload every unique Block (n).png referenced by every stage."""

        tiles_table = app.data.table('tiles')
        block_directory = str(tiles_table['block_directory'])
        tile_size = int(tiles_table['tile_size'])

        image_paths: set[str] = set()
        for stage in app.data.records('stages').values():
            for region in stage['terrain_regions']:
                block_number = int(region['block'])
                image_paths.add(
                    str(
                        Path(block_directory)
                        / f'Block ({block_number}).png'
                    )
                )

        for image_path in image_paths:
            cls._load_surface_for_path(
                app,
                image_path,
                tile_size,
            )

        return len(image_paths)

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
    def is_solid(self) -> bool:
        return self.collision_mode == 'solid'

    @property
    def is_one_way(self) -> bool:
        return self.collision_mode == 'one_way'

    def draw(
        self,
        screen: pygame.Surface,
        world: World,
        app: GameApp,
        camera: Camera,
    ) -> None:
        if not camera.is_world_rect_visible(
            self.x,
            self.y,
            self.width,
            self.height,
        ):
            return

        rect = camera.rect_from_world_center(
            self.x,
            self.y,
            self.width,
            self.height,
        )
        screen.blit(self._load_surface(app), rect.topleft)

    def _load_surface(self, app: GameApp) -> pygame.Surface:
        return self._load_surface_for_path(
            app,
            self.image_path,
            self.tile_size,
            block_number=self.block_number,
        )

    @classmethod
    def _load_surface_for_path(
        cls,
        app: GameApp,
        image_path: str,
        tile_size: int,
        *,
        block_number: int | None = None,
    ) -> pygame.Surface:
        """Load one source PNG once, scale it once, and reuse it forever."""

        path = Path(app.project_root) / image_path
        cache_key = (str(path), int(tile_size))

        cached = cls._surface_cache.get(cache_key)
        if cached is not None:
            return cached

        if not path.is_file():
            detail = (
                f'Block 번호: {block_number}\n'
                if block_number is not None
                else ''
            )
            raise FileNotFoundError(
                '지형 이미지를 찾을 수 없습니다.\n'
                f'{detail}'
                f'필요한 파일: {path}'
            )

        try:
            image = pygame.image.load(str(path)).convert_alpha()
        except pygame.error as error:
            raise RuntimeError(
                f'지형 이미지를 읽을 수 없습니다: {path}'
            ) from error

        if image.get_size() != (tile_size, tile_size):
            image = pygame.transform.scale(
                image,
                (tile_size, tile_size),
            )

        cls._surface_cache[cache_key] = image
        return image
