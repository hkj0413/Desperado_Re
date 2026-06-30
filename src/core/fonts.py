from __future__ import annotations

import pygame


class FontCache:
    """Caches fonts and prefers Windows Korean fonts when available."""

    def __init__(self) -> None:
        self._cache: dict[tuple[int, bool], pygame.font.Font] = {}

    def get(self, size: int, bold: bool = False) -> pygame.font.Font:
        key = (size, bold)
        if key not in self._cache:
            path = None
            for family in ('malgungothic', 'malgun gothic', 'nanumgothic', 'arial'):
                path = pygame.font.match_font(family, bold=bold)
                if path:
                    break

            font = pygame.font.Font(path, size) if path else pygame.font.Font(None, size)
            font.set_bold(bold)
            self._cache[key] = font
        return self._cache[key]
