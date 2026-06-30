from __future__ import annotations

from typing import TYPE_CHECKING

import pygame

if TYPE_CHECKING:
    from src.app import GameApp


class Scene:
    """Base interface for title, guide, play, pause, and future scenes."""

    def __init__(self, app: GameApp) -> None:
        self.app = app

    def on_enter(self) -> None:
        pass

    def on_exit(self) -> None:
        pass

    def handle_event(self, event: pygame.event.Event) -> None:
        pass

    def update(self, delta_seconds: float) -> None:
        pass

    def draw(self, screen: pygame.Surface) -> None:
        pass
