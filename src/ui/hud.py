from __future__ import annotations

from typing import TYPE_CHECKING

import pygame

if TYPE_CHECKING:
    from src.app import GameApp
    from src.core.camera import Camera
    from src.gameplay.entities.player import Player


class Hud:
    """Screen-space UI.

    These coordinates deliberately do not pass through Camera. The HUD stays
    fixed while the world scrolls behind it.
    """

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

        # Player health: screen coordinates, fixed in top-left.
        x, y, width, height = 32, 30, 270, 20
        ratio = player.hp / player.max_hp
        pygame.draw.rect(screen, (32, 32, 38), (x, y, width, height), border_radius=5)
        pygame.draw.rect(screen, (70, 190, 255), (x, y, int(width * ratio), height), border_radius=5)
        pygame.draw.rect(screen, (230, 235, 245), (x, y, width, height), width=1, border_radius=5)

        screen.blit(
            title_font.render(
                f'{player.display_name}  HP {player.hp}/{player.max_hp}',
                True,
                (240, 245, 250),
            ),
            (32, 56),
        )

        skills = ' / '.join(
            f'{index + 1}: {skill_id}'
            for index, skill_id in enumerate(player.skill_ids)
        )
        inventory = ', '.join(
            f'{item_id} x{amount}'
            for item_id, amount in player.inventory.items()
        ) or '없음'

        screen.blit(body_font.render(f'스킬  {skills}', True, (218, 223, 234)), (32, 94))
        screen.blit(body_font.render(f'인벤토리  {inventory}', True, (218, 223, 234)), (32, 120))

        # Debug-friendly proof of coordinate separation:
        # player.x/y = world position, camera.view_left/top = rendered world origin.
        coordinate_text = (
            f'월드 좌표  ({player.x:.0f}, {player.y:.0f})    '
            f'카메라 좌표  ({camera.view_left:.0f}, {camera.view_top:.0f})'
        )
        screen.blit(
            body_font.render(coordinate_text, True, (166, 191, 222)),
            (32, 818),
        )

        controls = 'A / D 또는 ← / → 이동   1 / 2 스킬   F5 데이터 리로드   ESC 메뉴'
        screen.blit(body_font.render(controls, True, (190, 198, 212)), (32, 848))

        if notice:
            text = title_font.render(notice, True, (255, 234, 158))
            screen.blit(text, (32, 155))
