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
    """Composes one stage after main/sub selection."""

    def __init__(self, app: GameApp, stage_id: str) -> None:
        super().__init__(app)
        self.stage_id = stage_id
        self.world: World | None = None
        self.camera: Camera | None = None
        self.player: Player | None = None
        self.hud = Hud()
        self.notice = ''
        self._notice_until = 0.0
        self.tile_size = 40

    def on_enter(self) -> None:
        if self.app.party is None:
            raise RuntimeError(
                'PlayScene must be entered through CharacterSelectScene.'
            )

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
            self.app.party,
            float(spawn['x']),
            float(spawn['y']),
        )
        self.world.add(self.player)

        for region in stage['terrain_regions']:
            kind = str(region['kind'])
            block_number = int(region['block'])
            definition = self.app.data.record('tiles', kind)

            for row_offset in range(int(region['rows'])):
                for col_offset in range(int(region['cols'])):
                    grid_col = int(region['col']) + col_offset
                    grid_row = int(region['row']) + row_offset

                    world_left = (
                        bounds.left + grid_col * self.tile_size
                    )
                    world_bottom = (
                        bounds.bottom + grid_row * self.tile_size
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
        self.world.collisions.register(
            'player',
            'enemy',
            self._on_player_enemy,
        )

        self.world.commit()
        self.camera.follow(self.player.x, self.player.y)

        self.set_notice(
            '←/→ 이동 · Space 점프 · A 기본 공격 · Z 메인/서브 교체 · H 테두리 디버그',
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

        if event.type == pygame.KEYDOWN and event.key == pygame.K_h:
            self.app.debug_draw_actor_bounds = (
                not self.app.debug_draw_actor_bounds
            )
            state = '켜짐' if self.app.debug_draw_actor_bounds else '꺼짐'
            self.set_notice(
                f'월드 액터 충돌 테두리: {state}',
                1.2,
            )
            return

        if self.player is None:
            return

        if event.type == pygame.KEYDOWN and event.key == pygame.K_z:
            # try_swap_character plays an effect only after a successful swap.
            self.set_notice(
                self.player.try_swap_character(self.app),
                1.4,
            )
            return

        result = self.player.handle_event(event, self.app)
        self._spawn_pending_player_skills()

        if result is not None:
            self.set_notice(result, 1.5)

    def update(self, delta_seconds: float) -> None:
        if self.world is None or self.camera is None:
            return

        self.world.update(delta_seconds, self.app)
        self._spawn_pending_player_skills()

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

    def _spawn_pending_player_skills(self) -> None:
        if self.player is None:
            return

        for skill_id in self.player.consume_pending_skill_ids():
            self._spawn_skill(skill_id)

    def _spawn_skill(self, skill_id: str) -> None:
        if self.player is None or self.world is None:
            return

        skill = self.app.data.record('skills', skill_id)
        behavior_type = str(skill['behavior_type'])

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
        else:
            self.set_notice(
                f"{skill['display_name']}은(는) 아직 구현되지 않은 "
                '행동 유형입니다.',
                2.0,
            )

    def _on_player_enemy(
        self,
        player: Player,
        enemy: Enemy,
        world: World,
        app: GameApp,
    ) -> None:
        """Apply enemy contact damage.

        Dash is stealth rather than ordinary invulnerability, so a dashing
        player is ignored entirely: no hit, no projectile-like collision side
        effect, and no enemy contact cooldown consumption.
        """

        if player.is_stealthed:
            return

        now = app.timer.game_time
        if not enemy.can_contact_attack(now):
            return

        if not player.take_damage(enemy.contact_damage, app):
            return

        enemy.mark_contact_attack(now)

        if player.hp <= 0:
            self.set_notice(
                f'{enemy.display_name} 접촉 피해 {enemy.contact_damage} · 사망',
                1.2,
            )
            return

        self.set_notice(
            f'{enemy.display_name} 접촉 피해 {enemy.contact_damage} · '
            '피격 경직',
            0.9,
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
        if self.player is None:
            return

        hit = projectile.register_enemy_hit(enemy, world) and enemy.take_damage(
            projectile.damage,
            app,
        )
        if not hit:
            return

        message = f'{enemy.display_name}에게 {projectile.damage} 피해'

        experience_reward = enemy.claim_experience_reward()
        if experience_reward > 0:
            total = self.player.add_experience(experience_reward)
            message += f' · 공용 경험치 +{experience_reward} ({total})'

        self.set_notice(message, 0.9)

    def set_notice(self, message: str, seconds: float) -> None:
        self.notice = message
        self._notice_until = self.app.timer.game_time + seconds
