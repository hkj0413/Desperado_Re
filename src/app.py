from __future__ import annotations

from pathlib import Path

import pygame

from src.core.audio_manager import AudioManager
from src.core.data_repository import DataRepository
from src.core.fonts import FontCache
from src.core.frame_timer import FrameTimer
from src.core.scene_manager import SceneManager
from src.gameplay.party import PartyManager


class GameApp:
    """Application root: owns shared services and the main loop."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root
        self.data = DataRepository(project_root / 'data')
        self.data.load_all()

        config = self.data.config()
        window = config['window']
        runtime = config['runtime']

        pygame.init()
        pygame.font.init()

        self.screen = pygame.display.set_mode(
            (int(window['width']), int(window['height']))
        )
        pygame.display.set_caption(str(window['title']))

        self.background_color = tuple(window['background_color'])
        self.fonts = FontCache()
        self.timer = FrameTimer(
            target_fps=int(runtime['target_fps']),
            max_delta_seconds=float(runtime['max_delta_seconds']),
        )
        self.audio = AudioManager(project_root, self.data)

        self.party: PartyManager | None = None
        self.scene_manager = SceneManager(self)
        self.running = True

        # World-actor collision bounds overlay. UI is drawn later by Hud and is
        # intentionally excluded from this flag.
        self.debug_draw_actor_bounds = False

        # Load all currently renderable PNGs before the first menu frame:
        # every configured animation for all registered characters and every
        # Block (n).png referenced by the stage tables.
        self._preload_visual_assets()

    def _preload_visual_assets(self) -> None:
        """Fill render caches once after pygame has a display surface.

        ``convert_alpha()`` requires a display mode, which is why preloading
        belongs here rather than at module import time.
        """

        from src.gameplay.character_assets import CharacterSpriteCache
        from src.gameplay.enemy_assets import EnemySpriteCache
        from src.gameplay.entities.terrain import TerrainBlock
        from src.gameplay.projectile_assets import ProjectileSpriteCache

        CharacterSpriteCache.preload_all(
            self,
            self.data.records('characters'),
        )
        EnemySpriteCache.preload_all(
            self,
            self.data.records('enemies'),
        )
        ProjectileSpriteCache.preload_all(
            self,
            self.data.records('skills'),
        )
        TerrainBlock.preload_all_stage_blocks(self)

    def start_party(
        self,
        main_character_id: str,
        sub_character_id: str,
    ) -> PartyManager:
        character_table = self.data.table('characters')
        character_definitions = character_table['records']
        shared_settings = character_table['shared_settings']
        item_definitions = self.data.records('items')

        self.party = PartyManager(
            main_character_id=main_character_id,
            sub_character_id=sub_character_id,
            character_definitions=character_definitions,
            item_definitions=item_definitions,
            shared_settings=shared_settings,
        )
        return self.party

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
        """F5 development reload for data tables and runtime asset caches."""
        from src.gameplay.character_assets import CharacterSpriteCache
        from src.gameplay.enemy_assets import EnemySpriteCache
        from src.gameplay.entities.terrain import TerrainBlock
        from src.gameplay.projectile_assets import ProjectileSpriteCache

        self.data.reload_all()
        self.audio.clear_cache()
        CharacterSpriteCache.clear_cache()
        EnemySpriteCache.clear_cache()
        ProjectileSpriteCache.clear_cache()
        TerrainBlock.clear_cache()
        self._preload_visual_assets()

    def stop(self) -> None:
        self.running = False
