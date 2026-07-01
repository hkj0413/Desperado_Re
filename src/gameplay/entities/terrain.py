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
    """One 40 x 40 terrain tile.

    floor:
    - solid collision on all sides

    platform:
    - one-way collision
    - landing works only from above
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

        image = self._load_surface(app)
        screen.blit(image, rect.topleft)

    def _load_surface(
        self,
        app: GameApp,
    ) -> pygame.Surface:
        """Load original Block (n).png once and scale to 40 x 40."""

        path = Path(app.project_root) / self.image_path

        cache_key = (
            str(path),
            self.tile_size,
        )

        cached = self._surface_cache.get(cache_key)

        if cached is not None:
            return cached

        if not path.is_file():
            raise FileNotFoundError(
                '지형 이미지를 찾을 수 없습니다.\n'
                f'필요한 파일: {path}\n'
                f'스테이지 block 번호: {self.block_number}'
            )

        try:
            image = pygame.image.load(
                str(path)
            ).convert_alpha()

        except pygame.error as error:
            raise RuntimeError(
                f'지형 이미지를 읽을 수 없습니다: {path}'
            ) from error

        if image.get_size() != (
            self.tile_size,
            self.tile_size,
        ):
            image = pygame.transform.scale(
                image,
                (
                    self.tile_size,
                    self.tile_size,
                ),
            )

        self._surface_cache[cache_key] = image
        return image