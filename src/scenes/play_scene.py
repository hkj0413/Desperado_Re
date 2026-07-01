from __future__ import annotations

from typing import TYPE_CHECKING

import pygame

from src.core.camera import Camera, WorldBounds
from src.core.scene import Scene
from src.core.world import World
from src.gameplay.entities.enemy import Enemy
from src.gameplay.entities.item_drop import ItemDrop
from src.gameplay.entities.player import Player
from src.gameplay.entities.portal import Portal
from src.gameplay.entities.projectile import Projectile
from src.gameplay.entities.terrain import TerrainBlock
from src.gameplay.factories import (
    create_enemy,
    create_item_drop,
    create_player,
)
from src.ui.hud import Hud

if TYPE_CHECKING:
    from src.app import GameApp


class PlayScene(Scene):
    """Composes one stage and owns its camera.

    - World, collision, and physics use WORLD coordinates.
    - Camera converts world coordinates to screen coordinates only in draw().
    - Terrain uses 20 x 20 grid tiles.
    - Each tile uses Block (n).png selected in stages.json.
    - Hud uses SCREEN coordinates and never scrolls.
    """

    def __init__(self, app: GameApp, stage_id: str) -> None:
        super().__init__(app)

        self.stage_id = stage_id
        self.world: World | None = None
        self.camera: Camera | None = None
        self.player: Player | None = None

        self.hud = Hud()
        self.notice = ''
        self._notice_until = 0.0

        self.tile_size = 20

    def on_enter(self) -> None:
        stage = self.app.data.record('stages', self.stage_id)

        bounds = WorldBounds.from_mapping(stage['world_bounds'])
        self.world = World(bounds)

        viewport_width, viewport_height = self.app.screen.get_size()

        self.camera = Camera(
            viewport_width,
            viewport_height,
            bounds,
        )

        tiles_table = self.app.data.table('tiles')
        self.tile_size = int(tiles_table['tile_size'])
        block_directory = str(tiles_table['block_directory'])

        spawn = stage['player_spawn']

        self.player = create_player(
            self.app,
            stage['player_character_id'],
            float(spawn['x']),
            float(spawn['y']),
        )

        self.world.add(self.player)

        # terrain_regions 하나는 cols × rows만큼 20 × 20 타일을 생성한다.
        #
        # 예:
        # {
        #   "kind": "floor",
        #   "block": 1,
        #   "col": 0,
        #   "row": 36,
        #   "cols": 320,
        #   "rows": 9
        # }
        #
        # 위 데이터는 Block (1).png를 320 × 9번 반복한다.
        for region in stage['terrain_regions']:
            kind = str(region['kind'])
            block_number = int(region['block'])

            definition = self.app.data.record(
                'tiles',
                kind,
            )

            for row_offset in range(int(region['rows'])):
                for col_offset in range(int(region['cols'])):
                    grid_col = int(region['col']) + col_offset
                    grid_row = int(region['row']) + row_offset

                    world_left = (
                            bounds.left
                            + grid_col * self.tile_size
                    )

                    # row 0은 월드 맨 아래다.
                    world_bottom = (
                            bounds.bottom
                            + grid_row * self.tile_size
                    )

                    self.world.add(
                        TerrainBlock(
                            kind=kind,
                            definition=definition,
                            world_left=world_left,
                            world_bottom=world_bottom,
                            tile_size=self.tile_size,
                            block_number=block_number,
                            block_directory=block_directory,
                            grid_col=grid_col,
                            grid_row=grid_row,
                        )
                    )

        for spawn_info in stage['enemy_spawns']:
            self.world.add(
                create_enemy(
                    self.app,
                    str(spawn_info['enemy_id']),
                    float(spawn_info['x']),
                    float(spawn_info['y']),
                )
            )

        for spawn_info in stage['item_spawns']:
            self.world.add(
                create_item_drop(
                    self.app,
                    str(spawn_info['item_id']),
                    float(spawn_info['x']),
                    float(spawn_info['y']),
                )
            )

        portal = stage['portal']

        self.world.add(
            Portal(
                float(portal['x']),
                float(portal['y']),
                float(portal['width']),
                float(portal['height']),
                str(portal['target_stage_id']),
            )
        )

        # floor / platform 충돌은 Player 내부에서 처리한다.
        # 여기서는 아이템, 포탈, 투사체 충돌만 등록한다.
        self.world.collisions.register(
            'player',
            'item',
            self._on_player_item,
        )

        self.world.collisions.register(
            'player',
            'portal',
            self._on_player_portal,
        )

        self.world.collisions.register(
            'player_projectile',
            'enemy',
            self._on_projectile_enemy,
        )

        self.world.commit()

        self.camera.follow(self.player.x, self.player.y)

        self.set_notice(
            'A/D 또는 ←/→ 이동 · ↑/Space 점프 · '
            'floor는 전방향 충돌 · platform은 착지만 충돌',
            5.0,
        )

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            from src.scenes.main_menu_scene import MainMenuScene

            self.app.scene_manager.change(MainMenuScene)
            return

        if event.type == pygame.KEYDOWN and event.key == pygame.K_F5:
            self.app.reload_data()

            self.set_notice(
                'JSON 데이터테이블을 다시 읽었습니다. '
                '현재 스테이지 배치는 다시 시작해야 적용됩니다.',
                3.0,
            )
            return

        if self.player is None:
            return

        skill_result = self.player.handle_event(event, self.app)

        if skill_result is None:
            return

        if skill_result in self.player.skill_ids:
            self._spawn_skill(skill_result)
        else:
            self.set_notice(skill_result, 1.5)

    def update(self, delta_seconds: float) -> None:
        if self.world is None or self.camera is None:
            return

        self.world.update(delta_seconds, self.app)

        if self.player is not None and self.player.alive:
            self.camera.follow(self.player.x, self.player.y)

        if self.app.timer.game_time > self._notice_until:
            self.notice = ''

    def draw(self, screen: pygame.Surface) -> None:
        if self.world is None or self.camera is None:
            return

        self.world.draw(screen, self.app, self.camera)

        if self.player is not None:
            self.hud.draw(
                screen,
                self.app,
                self.player,
                self.camera,
                self.notice,
            )

    def _spawn_skill(self, skill_id: str) -> None:
        if self.player is None or self.world is None:
            return

        skill = self.app.data.record('skills', skill_id)
        behavior_type = skill['behavior_type']

        if behavior_type.startswith('projectile'):
            self.world.add(
                Projectile(
                    skill_id,
                    skill,
                    self.player.x
                    + self.player.facing * (self.player.width * 0.55),
                    self.player.y,
                    self.player.facing,
                )
            )

            self.set_notice(
                f"{skill['display_name']} 사용",
                0.7,
            )

        else:
            self.set_notice(
                f"{skill['display_name']}은(는) 아직 구현되지 않은 "
                '행동 유형입니다.',
                2.0,
            )

    def _on_player_item(
        self,
        player: Player,
        item: ItemDrop,
        world: World,
        app: GameApp,
    ) -> None:
        message = player.add_item(
            item.item_id,
            1,
            item.definition,
        )

        world.remove(item)
        self.set_notice(message, 2.0)

    def _on_player_portal(
        self,
        player: Player,
        portal: Portal,
        world: World,
        app: GameApp,
    ) -> None:
        self.set_notice(
            f"포탈 감지: 다음에는 '{portal.target_stage_id}' "
            '로드 규칙을 연결합니다.',
            1.0,
        )

    def _on_projectile_enemy(
        self,
        projectile: Projectile,
        enemy: Enemy,
        world: World,
        app: GameApp,
    ) -> None:
        if projectile.register_enemy_hit(
            enemy,
            world,
        ) and enemy.take_damage(
            projectile.damage,
            app,
        ):
            self.set_notice(
                f'{enemy.display_name}에게 {projectile.damage} 피해',
                0.6,
            )

    def set_notice(self, message: str, seconds: float) -> None:
        self.notice = message
        self._notice_until = self.app.timer.game_time + seconds