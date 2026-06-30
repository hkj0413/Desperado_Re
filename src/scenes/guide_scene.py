from __future__ import annotations

import pygame

from src.core.scene import Scene


class GuideScene(Scene):
    LINES = (
        '이 프로젝트는 기존 Desperado의 기능만 참고하고 코드는 새로 구성한 뼈대입니다.',
        '',
        '실행 흐름',
        'main.py → GameApp → SceneManager → 현재 Scene → World → Entity / CollisionSystem',
        '',
        '데이터 흐름',
        'JSON 데이터테이블 → DataRepository 검증 → Factory → 런타임 Entity',
        '',
        '조작',
        '메뉴: ↑ ↓ / Enter',
        '플레이: A D 또는 ← → 이동, 1 2 스킬, F5 데이터 다시 읽기, ESC 메뉴',
        '',
        'Enter 또는 ESC를 누르면 메뉴로 돌아갑니다.',
    )

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type == pygame.KEYDOWN and event.key in (pygame.K_RETURN, pygame.K_ESCAPE):
            from src.scenes.main_menu_scene import MainMenuScene
            self.app.scene_manager.change(MainMenuScene)

    def draw(self, screen: pygame.Surface) -> None:
        heading_font = self.app.fonts.get(38, bold=True)
        body_font = self.app.fonts.get(22)
        screen.blit(heading_font.render('구조 안내', True, (235, 218, 158)), (90, 75))

        y = 150
        for line in self.LINES:
            if line in ('실행 흐름', '데이터 흐름', '조작'):
                text = self.app.fonts.get(25, bold=True).render(line, True, (122, 199, 255))
            else:
                text = body_font.render(line, True, (220, 226, 237))
            screen.blit(text, (100, y))
            y += 38
