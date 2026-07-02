from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import pygame

if TYPE_CHECKING:
    from src.app import GameApp


class ProjectileSpriteCache:
    """Caches optional projectile images.

    A projectile can omit ``image_path`` and will keep using its colored
    rectangle placeholder. When an image path is configured, the PNG is loaded
    and scaled once at startup or F5 reload, never during normal drawing.
    """

    _normal_cache: dict[tuple[str, int, int], pygame.Surface] = {}
    _flipped_cache: dict[tuple[str, int, int], pygame.Surface] = {}

    @classmethod
    def clear_cache(cls) -> None:
        cls._normal_cache.clear()
        cls._flipped_cache.clear()

    @classmethod
    def preload_all(
        cls,
        app: GameApp,
        skill_definitions: dict[str, dict[str, Any]],
    ) -> int:
        loaded = 0

        for definition in skill_definitions.values():
            projectile = definition.get('projectile')
            if not isinstance(projectile, dict):
                continue

            if cls._load_surface(app, projectile) is not None:
                loaded += 1

        return loaded

    @classmethod
    def get_surface(
        cls,
        app: GameApp,
        projectile_definition: dict[str, Any],
        direction: int,
    ) -> pygame.Surface | None:
        image = cls._load_surface(app, projectile_definition)
        if image is None:
            return None

        source_facing = str(
            projectile_definition.get('source_facing', 'right')
        ).lower()

        source_direction = -1 if source_facing == 'left' else 1
        if (1 if direction >= 0 else -1) == source_direction:
            return image

        key = cls._cache_key(app, projectile_definition)
        if key is None:
            return image

        flipped = cls._flipped_cache.get(key)
        if flipped is None:
            flipped = pygame.transform.flip(image, True, False)
            cls._flipped_cache[key] = flipped

        return flipped

    @classmethod
    def _load_surface(
        cls,
        app: GameApp,
        projectile_definition: dict[str, Any],
    ) -> pygame.Surface | None:
        key = cls._cache_key(app, projectile_definition)
        if key is None:
            return None

        cached = cls._normal_cache.get(key)
        if cached is not None:
            return cached

        path = Path(key[0])
        if not path.is_file():
            # Projectile art may not be prepared yet. Keep gameplay functional
            # by allowing the current placeholder rectangle to draw.
            return None

        try:
            image = pygame.image.load(str(path)).convert_alpha()
        except pygame.error as error:
            raise RuntimeError(
                f'투사체 이미지를 읽을 수 없습니다: {path}'
            ) from error

        target_size = (key[1], key[2])
        if image.get_size() != target_size:
            image = pygame.transform.scale(image, target_size)

        cls._normal_cache[key] = image
        return image

    @staticmethod
    def _cache_key(
        app: GameApp,
        projectile_definition: dict[str, Any],
    ) -> tuple[str, int, int] | None:
        image_path = projectile_definition.get('image_path')
        if not isinstance(image_path, str) or not image_path.strip():
            return None

        width = int(projectile_definition.get('draw_width', projectile_definition.get('width', 12)))
        height = int(projectile_definition.get('draw_height', projectile_definition.get('height', 8)))

        if width <= 0 or height <= 0:
            return None

        full_path = Path(app.project_root) / image_path
        return (str(full_path), width, height)
