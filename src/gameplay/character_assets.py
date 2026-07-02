from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import pygame

if TYPE_CHECKING:
    from src.app import GameApp


class CharacterSpriteCache:
    """Caches every configured character animation as display-ready surfaces.

    Frame count is discovered from files, not entered manually:
    ``Idle_SG (1).png``, ``Idle_SG (2).png`` ... continue until the first
    missing number. Frame numbers must therefore be consecutive.

    The cache stores both the normal and horizontally flipped surfaces. All
    configured character animations can be preloaded once during app startup,
    so drawing never opens image files during gameplay.
    """

    _frames_cache: dict[
        tuple[str, str, int, int],
        tuple[pygame.Surface, ...],
    ] = {}
    _flipped_cache: dict[
        tuple[str, str, int, int],
        tuple[pygame.Surface, ...],
    ] = {}

    @classmethod
    def clear_cache(cls) -> None:
        """Forget loaded frames after assets/data are changed during development."""
        cls._frames_cache.clear()
        cls._flipped_cache.clear()

    @classmethod
    def preload_all(
        cls,
        app: GameApp,
        character_definitions: dict[str, dict[str, Any]],
    ) -> int:
        """Preload every configured animation for every registered character.

        ``idle`` and ``walk`` are required gameplay animations, so a missing
        first frame raises a clear startup error. Other animations are optional:
        they are skipped when no ``(1)`` file exists and can still fall back to
        idle at runtime.
        """

        loaded_animation_sets = 0

        for character_id, definition in character_definitions.items():
            visual = definition['visual']
            animations = visual['animations']

            for animation_name, animation in animations.items():
                if not cls._first_frame_exists(app, visual, animation):
                    if animation_name in ('idle', 'walk'):
                        directory = Path(app.project_root) / str(
                            visual['directory']
                        )
                        expected = directory / (
                            f"{animation['file_stem']} (1).png"
                        )
                        raise FileNotFoundError(
                            '필수 캐릭터 애니메이션 이미지를 찾을 수 없습니다.\n'
                            f'캐릭터: {character_id}\n'
                            f'애니메이션: {animation_name}\n'
                            f'필요한 첫 파일: {expected}'
                        )
                    continue

                frames = cls._load_frames(app, visual, animation)
                cls._flipped_frames(app, visual, animation, frames)
                loaded_animation_sets += 1

        return loaded_animation_sets

    @classmethod
    def resolve_animation_name(
        cls,
        app: GameApp,
        definition: dict[str, Any],
        requested_name: str,
    ) -> str:
        """Return a usable animation id, falling back to idle when optional art
        is not present yet.
        """

        return cls._resolve_available_animation_name(
            app,
            definition['visual'],
            requested_name,
        )

    @classmethod
    def get_draw_offset(
        cls,
        definition: dict[str, Any],
        animation_name: str,
        facing: int,
    ) -> tuple[float, float]:
        """Return the visual-only offset in world pixels.

        Positive X moves the image right while facing right. By default that
        horizontal correction mirrors with the sprite when facing left.
        Positive Y moves the image upward in the bottom-left world coordinate
        system. Collider position and collision never change.
        """

        visual = definition['visual']
        animation = visual['animations'].get(animation_name, {})

        offset_x = float(visual.get('draw_offset_x', 0.0))
        offset_y = float(visual.get('draw_offset_y', 0.0))

        offset_x += float(animation.get('draw_offset_x', 0.0))
        offset_y += float(animation.get('draw_offset_y', 0.0))

        # Horizontal visual corrections always mirror with the character.
        # This is a project-wide rule, so JSON has no per-character mirror
        # switch to accidentally turn off.
        if facing < 0:
            offset_x = -offset_x

        return offset_x, offset_y

    @classmethod
    def get_frame(
        cls,
        app: GameApp,
        definition: dict[str, Any],
        animation_name: str,
        elapsed_seconds: float,
        facing: int,
        *,
        playback_speed: float = 1.0,
        loop: bool = True,
    ) -> pygame.Surface:
        """Return one cached animation frame.

        Missing optional animations such as ``attack`` or ``dash`` fall back to
        idle. ``playback_speed`` is used for attack-speed-scaled animation
        playback.
        """

        visual = definition['visual']
        animation_name = cls._resolve_available_animation_name(
            app,
            visual,
            animation_name,
        )
        animation = visual['animations'][animation_name]
        frames = cls._load_frames(app, visual, animation)

        frame_progress = int(
            max(0.0, elapsed_seconds)
            * float(animation['fps'])
            * max(0.0, float(playback_speed))
        )

        if loop:
            frame_index = frame_progress % len(frames)
        else:
            frame_index = min(frame_progress, len(frames) - 1)

        if facing < 0:
            frames = cls._flipped_frames(
                app,
                visual,
                animation,
                frames,
            )

        return frames[frame_index]

    @classmethod
    def get_animation_duration(
        cls,
        app: GameApp,
        definition: dict[str, Any],
        animation_name: str,
    ) -> float | None:
        """Return one non-looping animation cycle length when art exists."""

        visual = definition['visual']
        animations = visual['animations']

        if animation_name not in animations:
            return None

        animation = animations[animation_name]
        if not cls._first_frame_exists(app, visual, animation):
            return None

        frames = cls._load_frames(app, visual, animation)
        fps = float(animation['fps'])
        return len(frames) / fps if fps > 0.0 else None

    @classmethod
    def get_preview(
        cls,
        app: GameApp,
        definition: dict[str, Any],
    ) -> pygame.Surface:
        return cls.get_frame(
            app,
            definition,
            'idle',
            elapsed_seconds=0.0,
            facing=1,
        )

    @classmethod
    def _resolve_available_animation_name(
        cls,
        app: GameApp,
        visual: dict[str, Any],
        requested_name: str,
    ) -> str:
        animations = visual['animations']

        if (
            requested_name in animations
            and cls._first_frame_exists(
                app,
                visual,
                animations[requested_name],
            )
        ):
            return requested_name

        return 'idle'

    @classmethod
    def _first_frame_exists(
        cls,
        app: GameApp,
        visual: dict[str, Any],
        animation: dict[str, Any],
    ) -> bool:
        directory = Path(app.project_root) / str(visual['directory'])
        stem = str(animation['file_stem'])
        return (directory / f'{stem} (1).png').is_file()

    @classmethod
    def _load_frames(
        cls,
        app: GameApp,
        visual: dict[str, Any],
        animation: dict[str, Any],
    ) -> tuple[pygame.Surface, ...]:
        directory = Path(app.project_root) / str(visual['directory'])
        stem = str(animation['file_stem'])
        width = int(visual['draw_width'])
        height = int(visual['draw_height'])

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
                    f'캐릭터 이미지를 읽을 수 없습니다: {path}'
                ) from error

            if image.get_size() != (width, height):
                image = pygame.transform.scale(
                    image,
                    (width, height),
                )

            frames.append(image)
            frame_number += 1

        if not frames:
            expected = directory / f'{stem} (1).png'
            raise FileNotFoundError(
                '캐릭터 애니메이션 이미지를 찾을 수 없습니다.\n'
                f'필요한 첫 파일: {expected}'
            )

        result = tuple(frames)
        cls._frames_cache[cache_key] = result
        return result

    @classmethod
    def _flipped_frames(
        cls,
        app: GameApp,
        visual: dict[str, Any],
        animation: dict[str, Any],
        original_frames: tuple[pygame.Surface, ...],
    ) -> tuple[pygame.Surface, ...]:
        directory = Path(app.project_root) / str(visual['directory'])
        stem = str(animation['file_stem'])
        width = int(visual['draw_width'])
        height = int(visual['draw_height'])

        cache_key = (str(directory), stem, width, height)
        cached = cls._flipped_cache.get(cache_key)
        if cached is not None:
            return cached

        flipped = tuple(
            pygame.transform.flip(frame, True, False)
            for frame in original_frames
        )
        cls._flipped_cache[cache_key] = flipped
        return flipped
