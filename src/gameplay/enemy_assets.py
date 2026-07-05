from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import pygame

if TYPE_CHECKING:
    from src.app import GameApp


class EnemySpriteCache:
    """Caches enemy animation frames.

    Enemy source artwork is authored facing LEFT. Therefore:
    - facing < 0: use the source frame as-is
    - facing > 0: use the precomputed horizontally flipped frame

    Missing enemy art is intentionally allowed while monsters are still being
    prototyped; Enemy.draw() falls back to the existing colored rectangle.
    """

    _frames_cache: dict[
        tuple[str, str, int, int],
        tuple[pygame.Surface, ...],
    ] = {}
    _flipped_cache: dict[
        tuple[str, str, int, int],
        tuple[pygame.Surface, ...],
    ] = {}
    _first_frame_exists_cache: dict[tuple[str, str], bool] = {}
    _animation_duration_cache: dict[tuple[str, str, int, int, float], float] = {}

    @classmethod
    def clear_cache(cls) -> None:
        cls._frames_cache.clear()
        cls._flipped_cache.clear()
        cls._first_frame_exists_cache.clear()
        cls._animation_duration_cache.clear()

    @classmethod
    def resolve_animation_name(
        cls,
        app: GameApp,
        definition: dict[str, Any],
        requested_name: str,
    ) -> str | None:
        """Resolve a configured enemy animation, falling back to Idle.

        Drawing uses this once so the frame cache and the visual-size/offset
        lookup always refer to the same animation.
        """

        visual = definition.get('visual', {})
        return cls._resolve_available_animation_name(
            app,
            visual,
            requested_name,
        )

    @staticmethod
    def get_draw_settings(
        definition: dict[str, Any],
        animation_name: str | None,
    ) -> tuple[float, float, float, float]:
        """Return visual-only width, height, X offset and Y offset.

        Values are read from ``visual`` first. An animation can optionally
        override any of them, which makes it possible to correct a single
        oversized/shifted attack or death sheet without changing collision.
        Positive X moves right; positive Y moves upward in world space.
        """

        visual = definition.get('visual', {})
        animations = visual.get('animations', {})
        animation = (
            animations.get(animation_name, {})
            if isinstance(animation_name, str)
            else {}
        )
        if not isinstance(animation, dict):
            animation = {}

        width = float(
            animation.get(
                'draw_width',
                visual.get('draw_width', visual.get('width', 1)),
            )
        )
        height = float(
            animation.get(
                'draw_height',
                visual.get('draw_height', visual.get('height', 1)),
            )
        )
        offset_x = float(
            visual.get('draw_offset_x', 0.0)
        ) + float(animation.get('draw_offset_x', 0.0))
        offset_y = float(
            visual.get('draw_offset_y', 0.0)
        ) + float(animation.get('draw_offset_y', 0.0))

        return max(1.0, width), max(1.0, height), offset_x, offset_y

    @classmethod
    def preload_all(
        cls,
        app: GameApp,
        enemy_definitions: dict[str, dict[str, Any]],
    ) -> int:
        loaded_sets = 0

        for definition in enemy_definitions.values():
            visual = definition.get('visual', {})
            animations = visual.get('animations', {})

            for animation in animations.values():
                if not cls._first_frame_exists(app, visual, animation):
                    continue

                frames = cls._load_frames(app, visual, animation)
                cls._flipped_frames(visual, animation, frames)
                loaded_sets += 1

        return loaded_sets

    @classmethod
    def get_animation_duration(
        cls,
        app: GameApp,
        definition: dict[str, Any],
        animation_name: str,
    ) -> float:
        """Return one non-looping animation pass in seconds.

        Patrol waits use the actual Idle frame count and FPS rather than an
        arbitrary timer. The result is cached, and this method is called only
        when an enemy enters a deliberate waiting state, never every frame.
        """

        visual = definition.get('visual', {})
        resolved_name = cls._resolve_available_animation_name(
            app,
            visual,
            animation_name,
        )
        if resolved_name is None:
            return 0.0

        animation = visual['animations'][resolved_name]
        fps = max(0.0, float(animation.get('fps', 0.0)))
        if fps <= 0.0:
            return 0.0

        directory = str(visual.get('directory', ''))
        stem = str(animation.get('file_stem', ''))
        width = int(
            animation.get('draw_width', visual.get('draw_width', 0))
        )
        height = int(
            animation.get('draw_height', visual.get('draw_height', 0))
        )
        cache_key = (directory, stem, width, height, fps)
        cached = cls._animation_duration_cache.get(cache_key)
        if cached is not None:
            return cached

        frames = cls._load_frames(app, visual, animation)
        duration = len(frames) / fps
        cls._animation_duration_cache[cache_key] = duration
        return duration

    @classmethod
    def get_frame(
        cls,
        app: GameApp,
        definition: dict[str, Any],
        animation_name: str,
        elapsed_seconds: float,
        facing: int,
        *,
        force_first_frame: bool = False,
        loop: bool = True,
    ) -> pygame.Surface | None:
        visual = definition.get('visual', {})
        animation_name = cls._resolve_available_animation_name(
            app,
            visual,
            animation_name,
        )

        if animation_name is None:
            return None

        animation = visual['animations'][animation_name]
        frames = cls._load_frames(app, visual, animation)

        if force_first_frame:
            frame_index = 0
        else:
            fps = max(0.0, float(animation.get('fps', 0.0)))
            progress = int(max(0.0, elapsed_seconds) * fps)
            frame_index = progress % len(frames) if loop else min(
                progress,
                len(frames) - 1,
            )

        # Enemy source frames face LEFT. Only right-facing enemies use flips.
        if facing > 0:
            frames = cls._flipped_frames(visual, animation, frames)

        return frames[frame_index]

    @classmethod
    def _resolve_available_animation_name(
        cls,
        app: GameApp,
        visual: dict[str, Any],
        requested_name: str,
    ) -> str | None:
        animations = visual.get('animations', {})

        if (
            requested_name in animations
            and cls._first_frame_exists(
                app,
                visual,
                animations[requested_name],
            )
        ):
            return requested_name

        if (
            'idle' in animations
            and cls._first_frame_exists(
                app,
                visual,
                animations['idle'],
            )
        ):
            return 'idle'

        return None

    @classmethod
    def _first_frame_exists(
        cls,
        app: GameApp,
        visual: dict[str, Any],
        animation: dict[str, Any],
    ) -> bool:
        directory_value = visual.get('directory')
        stem_value = animation.get('file_stem')

        if not isinstance(directory_value, str) or not directory_value:
            return False
        if not isinstance(stem_value, str) or not stem_value:
            return False

        directory = Path(app.project_root) / directory_value
        cache_key = (str(directory), stem_value)

        cached = cls._first_frame_exists_cache.get(cache_key)
        if cached is not None:
            return cached

        exists = (directory / f'{stem_value} (1).png').is_file()
        cls._first_frame_exists_cache[cache_key] = exists
        return exists

    @classmethod
    def _load_frames(
        cls,
        app: GameApp,
        visual: dict[str, Any],
        animation: dict[str, Any],
    ) -> tuple[pygame.Surface, ...]:
        directory = Path(app.project_root) / str(visual['directory'])
        stem = str(animation['file_stem'])
        width = int(
            animation.get('draw_width', visual['draw_width'])
        )
        height = int(
            animation.get('draw_height', visual['draw_height'])
        )

        cache_key = (str(directory), stem, width, height)
        cached = cls._frames_cache.get(cache_key)
        if cached is not None:
            return cached

        frames: list[pygame.Surface] = []
        frame_number = 1

        while True:
            path = directory / f'{stem} ({frame_number}).png'
            if not path.is_file():
                break

            try:
                image = pygame.image.load(str(path)).convert_alpha()
            except pygame.error as error:
                raise RuntimeError(
                    f'몬스터 이미지를 읽을 수 없습니다: {path}'
                ) from error

            if image.get_size() != (width, height):
                image = pygame.transform.scale(image, (width, height))

            frames.append(image)
            frame_number += 1

        if not frames:
            expected = directory / f'{stem} (1).png'
            raise FileNotFoundError(
                '몬스터 애니메이션 이미지를 찾을 수 없습니다.\n'
                f'필요한 첫 파일: {expected}'
            )

        result = tuple(frames)
        cls._frames_cache[cache_key] = result
        return result

    @classmethod
    def _flipped_frames(
        cls,
        visual: dict[str, Any],
        animation: dict[str, Any],
        original_frames: tuple[pygame.Surface, ...],
    ) -> tuple[pygame.Surface, ...]:
        directory = str(visual['directory'])
        stem = str(animation['file_stem'])
        width = int(
            animation.get('draw_width', visual['draw_width'])
        )
        height = int(
            animation.get('draw_height', visual['draw_height'])
        )

        cache_key = (directory, stem, width, height)
        cached = cls._flipped_cache.get(cache_key)
        if cached is not None:
            return cached

        flipped = tuple(
            pygame.transform.flip(frame, True, False)
            for frame in original_frames
        )
        cls._flipped_cache[cache_key] = flipped
        return flipped
