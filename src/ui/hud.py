from __future__ import annotations

from typing import TYPE_CHECKING

import pygame

if TYPE_CHECKING:
    from src.app import GameApp
    from src.core.camera import Camera
    from src.gameplay.entities.player import Player


class Hud:
    """Screen-space UI. It never moves with the scrolling world."""

    _TEXT_CACHE_LIMIT = 512

    def __init__(self) -> None:
        # Font rasterization is much more expensive than blitting an existing
        # surface. Most HUD strings repeat across hundreds of frames, so keep a
        # small bounded cache keyed by the exact rendered appearance.
        self._text_cache: dict[
            tuple[int, str, tuple[int, int, int]],
            pygame.Surface,
        ] = {}

    def _render_cached(
        self,
        font: pygame.font.Font,
        text: str,
        color: tuple[int, int, int],
    ) -> pygame.Surface:
        key = (id(font), text, color)
        cached = self._text_cache.get(key)
        if cached is not None:
            return cached

        if len(self._text_cache) >= self._TEXT_CACHE_LIMIT:
            # A bounded cache avoids accumulating unique notices forever while
            # retaining the common steady-state HUD values.
            self._text_cache.clear()

        rendered = font.render(text, True, color)
        self._text_cache[key] = rendered
        return rendered

    def draw(
        self,
        screen: pygame.Surface,
        app: GameApp,
        player: Player,
        camera: Camera,
        notice: str,
    ) -> None:
        title_font = app.fonts.get(24, bold=True)
        body_font = app.fonts.get(18)

        # Shared player HP: full maximum width stays visible in bright green,
        # while missing HP is covered from the right by a darker green so the
        # player can still read the maximum capacity at a glance.
        x, y, width, height = 32, 30, 160, 34
        hp_text = f'{player.hp}/{player.max_hp}'
        hp_ratio = 0.0
        if player.max_hp > 0:
            hp_ratio = max(0.0, min(1.0, player.hp / player.max_hp))

        pygame.draw.rect(
            screen,
            (42, 126, 62),
            (x, y, width, height),
            border_radius=3,
        )

        missing_width = int(round(width * (1.0 - hp_ratio)))
        if missing_width > 0:
            pygame.draw.rect(
                screen,
                (24, 86, 40),
                (x + width - missing_width, y, missing_width, height),
                border_top_right_radius=3,
                border_bottom_right_radius=3,
            )

        pygame.draw.rect(
            screen,
            (18, 66, 30),
            (x, y, width, height),
            width=2,
            border_radius=3,
        )
        hp_surface = self._render_cached(title_font, hp_text, (244, 255, 244))
        hp_rect = hp_surface.get_rect(
            center=(x + width / 2, y + height / 2)
        )
        screen.blit(hp_surface, hp_rect)

        active_slot = '메인' if player.party.active_slot == 'main' else '서브'
        main_name = player.party.definition_for('main')['display_name']
        sub_name = player.party.definition_for('sub')['display_name']

        screen.blit(
            self._render_cached(
                body_font,
                f'공유 경험치  {player.experience}',
                (164, 223, 255),
            ),
            (32, 82),
        )
        screen.blit(
            self._render_cached(
                body_font,
                f'공유 레벨 {player.party.shared_level}   강화 {player.party.shared_enhancement_level}',
                (164, 223, 255),
            ),
            (32, 108),
        )
        screen.blit(
            self._render_cached(
                body_font,
                f'현재: {player.display_name} ({active_slot})',
                (255, 235, 169),
            ),
            (32, 134),
        )
        screen.blit(
            self._render_cached(
                body_font,
                f'메인: {main_name}   서브: {sub_name}',
                (218, 223, 234),
            ),
            (32, 160),
        )

        ability_text = self._ability_text(app, player)
        screen.blit(
            self._render_cached(
                body_font,
                ability_text,
                (218, 223, 234),
            ),
            (32, 186),
        )

        ammo = ', '.join(
            f'{ammo_type} {amount}/{player.party.active_runtime.max_ammo.get(ammo_type, amount)}'
            for ammo_type, amount in player.ammo.items()
        ) or '없음'
        screen.blit(
            self._render_cached(
                body_font,
                f'탄약  {ammo}  ← 캐릭터별',
                (218, 223, 234),
            ),
            (32, 212),
        )

        hotbar = self._hotbar_text(player)
        screen.blit(
            self._render_cached(
                body_font,
                f'공용 핫바  {hotbar}',
                (218, 223, 234),
            ),
            (32, 238),
        )
        screen.blit(
            self._render_cached(
                body_font,
                f'상태: {self._state_label(player.display_state)}  '
                f'공격속도 x{player.attack_speed_multiplier:.2f}',
                (166, 191, 222),
            ),
            (32, 264),
        )

        coordinate_text = (
            f'월드 좌표 ({player.x:.0f}, {player.y:.0f})    '
            f'카메라 좌표 ({camera.view_left:.0f}, '
            f'{camera.view_bottom:.0f})    '
            f'착지: {"예" if player.is_grounded else "아니오"}'
        )
        screen.blit(
            body_font.render(
                coordinate_text,
                True,
                (166, 191, 222),
            ),
            (32, 818),
        )

        controls_line_1 = (
            '←/→ 이동   Space 점프   Left Shift 대시   ↑ 미사용   '
            'R 장전   A 기본 공격   S/D 스킬   X 고유 스킬   C 궁극기'
        )
        controls_line_2 = (
            'W 선택 아이템 사용   Q/E 핫바 이동   Z 캐릭터 교체   '
            'H 테두리 디버그   F5 데이터 리로드   ESC 메뉴'
        )
        screen.blit(
            self._render_cached(
                body_font,
                controls_line_1,
                (190, 198, 212),
            ),
            (32, 844),
        )
        screen.blit(
            self._render_cached(
                body_font,
                controls_line_2,
                (190, 198, 212),
            ),
            (32, 868),
        )

        if notice:
            text = self._render_cached(
                title_font,
                notice,
                (255, 234, 158),
            )
            screen.blit(text, (32, 292))

    @staticmethod
    def _ability_text(app: GameApp, player: Player) -> str:
        parts: list[str] = []
        for key, binding in (
            ('A', 'basic'),
            ('S', 'skill_s'),
            ('D', 'skill_d'),
            ('X', 'main_unique'),
            ('C', 'main_ultimate'),
        ):
            skill_id = player.ability_id_for(binding)
            if skill_id is None:
                continue
            name = app.data.record('skills', skill_id)['display_name']
            parts.append(f'{key}: {name}')

        return '스킬  ' + (' / '.join(parts) if parts else '미배정')

    @staticmethod
    def _hotbar_text(player: Player) -> str:
        entries: list[str] = []
        selected = player.party.selected_hotbar_item_id

        for item_id in player.party.hotbar_item_ids:
            amount = player.party.shared_inventory.get(item_id, 0)
            marker = '▶' if item_id == selected else ' '
            entries.append(f'{marker}{item_id} x{amount}')

        return ' / '.join(entries) if entries else '비어 있음'

    @staticmethod
    def _state_label(state: str) -> str:
        labels = {
            'idle': '대기',
            'walk': '이동',
            'attack': '공격 중',
            'skill': '스킬 사용 중',
            'reload': '장전 중',
            'dash': '대시 중',
            'jump': '점프',
            'fall': '추락',
            'hit': '피격 경직 · 무적',
            'dead': '사망',
            'respawn_wait': '리스폰 대기',
        }
        return labels.get(state, state)
