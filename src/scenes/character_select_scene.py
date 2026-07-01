from __future__ import annotations

from typing import TYPE_CHECKING

import pygame

from src.core.scene import Scene
from src.gameplay.character_assets import CharacterSpriteCache

if TYPE_CHECKING:
    from src.app import GameApp


class CharacterSelectScene(Scene):
    """Select one main and one sub character from up to four records."""

    def __init__(self, app: GameApp) -> None:
        super().__init__(app)

        self.character_ids = list(
            self.app.data.records('characters').keys()
        )
        if len(self.character_ids) < 2:
            raise RuntimeError(
                '캐릭터 선택에는 characters.json에 최소 2명이 필요합니다.'
            )

        self.main_index = 0
        self.sub_index = 1
        self.editing_slot = 'main'
        self.notice = ''

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type != pygame.KEYDOWN:
            return

        if event.key in (pygame.K_LEFT, pygame.K_RIGHT):
            self.editing_slot = (
                'sub'
                if self.editing_slot == 'main'
                else 'main'
            )
            return

        if event.key == pygame.K_UP:
            self._change_selected_character(-1)
            return

        if event.key == pygame.K_DOWN:
            self._change_selected_character(1)
            return

        if event.key in (pygame.K_RETURN, pygame.K_SPACE):
            main_id = self.character_ids[self.main_index]
            sub_id = self.character_ids[self.sub_index]

            if main_id == sub_id:
                self.notice = '메인과 서브는 서로 다른 캐릭터여야 합니다.'
                return

            self.app.start_party(main_id, sub_id)

            from src.scenes.play_scene import PlayScene
            self.app.scene_manager.change(
                PlayScene,
                stage_id='prototype_stage',
            )
            return

        if event.key == pygame.K_ESCAPE:
            from src.scenes.main_menu_scene import MainMenuScene
            self.app.scene_manager.change(MainMenuScene)

    def _change_selected_character(self, direction: int) -> None:
        target_attr = (
            'main_index'
            if self.editing_slot == 'main'
            else 'sub_index'
        )
        other_index = (
            self.sub_index
            if self.editing_slot == 'main'
            else self.main_index
        )

        candidate = getattr(self, target_attr)
        for _ in range(len(self.character_ids)):
            candidate = (
                candidate + direction
            ) % len(self.character_ids)

            if candidate != other_index:
                setattr(self, target_attr, candidate)
                return

    def draw(self, screen: pygame.Surface) -> None:
        width, height = screen.get_size()

        title_font = self.app.fonts.get(48, bold=True)
        heading_font = self.app.fonts.get(28, bold=True)
        body_font = self.app.fonts.get(21)
        small_font = self.app.fonts.get(18)

        title = title_font.render(
            '캐릭터 선택',
            True,
            (235, 218, 158),
        )
        screen.blit(title, title.get_rect(center=(width // 2, 80)))

        help_text = body_font.render(
            '← / → 슬롯 선택   ↑ / ↓ 캐릭터 선택   Enter 게임 시작   Esc 뒤로',
            True,
            (190, 202, 220),
        )
        screen.blit(
            help_text,
            help_text.get_rect(center=(width // 2, 135)),
        )

        self._draw_slot(
            screen,
            x=220,
            y=220,
            slot_name='MAIN',
            character_id=self.character_ids[self.main_index],
            selected=self.editing_slot == 'main',
            heading_font=heading_font,
            body_font=body_font,
            small_font=small_font,
        )

        self._draw_slot(
            screen,
            x=980,
            y=220,
            slot_name='SUB',
            character_id=self.character_ids[self.sub_index],
            selected=self.editing_slot == 'sub',
            heading_font=heading_font,
            body_font=body_font,
            small_font=small_font,
        )

        candidate_text = '등록 캐릭터: ' + ' / '.join(
            self.app.data.record('characters', character_id)['display_name']
            for character_id in self.character_ids
        )
        candidates = small_font.render(
            candidate_text,
            True,
            (160, 179, 204),
        )
        screen.blit(
            candidates,
            candidates.get_rect(center=(width // 2, 760)),
        )

        if self.notice:
            notice = body_font.render(
                self.notice,
                True,
                (255, 170, 145),
            )
            screen.blit(
                notice,
                notice.get_rect(center=(width // 2, 820)),
            )

    def _draw_slot(
        self,
        screen: pygame.Surface,
        *,
        x: int,
        y: int,
        slot_name: str,
        character_id: str,
        selected: bool,
        heading_font: pygame.font.Font,
        body_font: pygame.font.Font,
        small_font: pygame.font.Font,
    ) -> None:
        definition = self.app.data.record('characters', character_id)
        visual = definition['visual']

        panel_rect = pygame.Rect(
            x,
            y,
            400,
            470,
        )

        border = (
            (255, 229, 147)
            if selected
            else (91, 108, 135)
        )
        fill = (
            (39, 46, 62)
            if selected
            else (31, 36, 49)
        )

        pygame.draw.rect(
            screen,
            fill,
            panel_rect,
            border_radius=12,
        )
        pygame.draw.rect(
            screen,
            border,
            panel_rect,
            width=3,
            border_radius=12,
        )

        slot_text = heading_font.render(
            slot_name,
            True,
            border,
        )
        screen.blit(
            slot_text,
            slot_text.get_rect(center=(panel_rect.centerx, y + 42)),
        )

        image = CharacterSpriteCache.get_preview(
            self.app,
            definition,
        )
        image_rect = image.get_rect(
            center=(panel_rect.centerx, y + 190)
        )
        screen.blit(image, image_rect)

        name_text = heading_font.render(
            str(definition['display_name']),
            True,
            (238, 242, 249),
        )
        screen.blit(
            name_text,
            name_text.get_rect(center=(panel_rect.centerx, y + 310)),
        )

        stats = definition['stats']
        shared_collider = self.app.data.table('characters')['shared_settings']['collider']
        detail_lines = (
            f'이동속도: {stats["move_speed"]:.0f}',
            f'충돌 크기: {int(shared_collider["width"])} × {int(shared_collider["height"])}',
            '표시 크기: 170 × 170',
        )

        for index, line in enumerate(detail_lines):
            detail = small_font.render(
                line,
                True,
                (190, 202, 220),
            )
            screen.blit(
                detail,
                detail.get_rect(
                    center=(panel_rect.centerx, y + 360 + index * 30)
                ),
            )
