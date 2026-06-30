from __future__ import annotations

from pathlib import Path
from typing import NoReturn

import pygame

from src.core.data_repository import DataRepository
from src.core.fonts import FontCache
from src.core.frame_timer import FrameTimer
from src.core.scene_manager import SceneManager


class GameApp:
    """Application root: creates services and runs the one main loop."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root
        self.data = DataRepository(project_root / 'data')
        self.data.load_all()

        config = self.data.config()
        window = config['window']
        runtime = config['runtime']

        pygame.init()
        pygame.font.init()

        self.screen = pygame.display.set_mode((window['width'], window['height']))
        pygame.display.set_caption(window['title'])

        self.background_color = tuple(window['background_color'])
        self.fonts = FontCache()
        self.timer = FrameTimer(
            target_fps=runtime['target_fps'],
            max_delta_seconds=runtime['max_delta_seconds'],
        )
        self.scene_manager = SceneManager(self)
        self.running = True

    def run(self) -> None:
        from src.scenes.main_menu_scene import MainMenuScene

        self.scene_manager.change(MainMenuScene)

        while self.running:
            delta_seconds = self.timer.begin_frame()

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.stop()
                    break

                current_scene = self.scene_manager.current
                if current_scene is not None:
                    current_scene.handle_event(event)

            current_scene = self.scene_manager.current
            if current_scene is not None and self.running:
                current_scene.update(delta_seconds)

                self.screen.fill(self.background_color)
                current_scene.draw(self.screen)
                pygame.display.flip()

            self.timer.end_frame()

        pygame.quit()

    def reload_data(self) -> None:
        """F5 development reload. Existing entities retain their runtime state."""
        self.data.reload_all()

    def stop(self) -> None:
        self.running = False
