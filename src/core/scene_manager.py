from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar

from src.core.scene import Scene

if TYPE_CHECKING:
    from src.app import GameApp


TScene = TypeVar('TScene', bound=Scene)


class SceneManager:
    """Owns exactly one active scene; scenes never call each other directly."""

    def __init__(self, app: GameApp) -> None:
        self._app = app
        self.current: Scene | None = None

    def change(self, scene_type: type[TScene], **kwargs: object) -> None:
        if self.current is not None:
            self.current.on_exit()

        self.current = scene_type(self._app, **kwargs)
        self.current.on_enter()
