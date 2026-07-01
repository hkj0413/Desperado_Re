from __future__ import annotations

import pygame

from src.core.scene import Scene


class MainMenuScene(Scene):
    MENU_ITEMS = (
        ('시작', 'play'),
        ('조작법', 'guide'),
        ('종료', 'quit'),
    )

    def __init__(self, app) -> None:
        super().__init__(app)
        self.selected_index = 0

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type != pygame.KEYDOWN:
            return

        if event.key == pygame.K_UP:
            self.selected_index = (
                self.selected_index - 1
            ) % len(self.MENU_ITEMS)

        elif event.key == pygame.K_DOWN:
            self.selected_index = (
                self.selected_index + 1
            ) % len(self.MENU_ITEMS)

        elif event.key in (pygame.K_RETURN, pygame.K_SPACE):
            self._activate_selected()

        elif event.key == pygame.K_ESCAPE:
            self.app.stop()

    def _activate_selected(self) -> None:
        action = self.MENU_ITEMS[self.selected_index][1]

        if action == 'play':
            from src.scenes.character_select_scene import CharacterSelectScene
            self.app.scene_manager.change(CharacterSelectScene)

        elif action == 'guide':
            from src.scenes.guide_scene import GuideScene
            self.app.scene_manager.change(GuideScene)

        elif action == 'quit':
            self.app.stop()

    def draw(self, screen: pygame.Surface) -> None:
        width, height = screen.get_size()

        title_font = self.app.fonts.get(58, bold=True)
        subtitle_font = self.app.fonts.get(23)
        menu_font = self.app.fonts.get(30, bold=True)

        title = title_font.render(
            'Desperado Re:',
            True,
            (235, 218, 158),
        )
        subtitle = subtitle_font.render(
            '2D Adventure',
            True,
            (180, 192, 214),
        )

        screen.blit(
            title,
            title.get_rect(center=(width // 2, 220)),
        )
        screen.blit(
            subtitle,
            subtitle.get_rect(center=(width // 2, 280)),
        )

        for index, (label, _) in enumerate(self.MENU_ITEMS):
            selected = index == self.selected_index
            color = (
                (255, 238, 166)
                if selected
                else (218, 224, 235)
            )
            prefix = '▶  ' if selected else '    '

            text = menu_font.render(
                prefix + label,
                True,
                color,
            )
            screen.blit(
                text,
                text.get_rect(
                    center=(width // 2, 390 + index * 58)
                ),
            )

        footer = subtitle_font.render(
            '↑ ↓ 선택   Enter 결정   Esc 종료',
            True,
            (150, 160, 178),
        )
        screen.blit(
            footer,
            footer.get_rect(center=(width // 2, 760)),
        )
