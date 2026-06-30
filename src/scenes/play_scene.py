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
from src.gameplay.factories import create_enemy, create_item_drop, create_player
from src.ui.hud import Hud

if TYPE_CHECKING:
    from src.app import GameApp


class PlayScene(Scene):
    """Composes one stage and owns its camera.

    - `World` and every Entity use WORLD coordinates.
    - `Camera` follows the player and converts world -> screen only in draw().
    - `Hud` always uses SCREEN coordinates, so it never scrolls.
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

    def on_enter(self) -> None:
        stage = self.app.data.record('stages', self.stage_id)
        bounds = WorldBounds.from_mapping(stage['world_bounds'])
        self.world = World(bounds)

        viewport_width, viewport_height = self.app.screen.get_size()
        self.camera = Camera(viewport_width, viewport_height, bounds)

        spawn = stage['player_spawn']
        self.player = create_player(
            self.app,
            stage['player_character_id'],
            float(spawn['x']),
            float(spawn['y']),
        )
        self.world.add(self.player)

        # Terrain JSON stores x/y as its world-space top-left corner.
        # Entity positions use center coordinates, so convert once here.
        for block in stage['terrain_blocks']:
            self.world.add(
                TerrainBlock(
                    float(block['x']) + float(block['width']) * 0.5,
                    float(block['y']) + float(block['height']) * 0.5,
                    float(block['width']),
                    float(block['height']),
                    str(block.get('kind', 'floor')),
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

        # Category pairs stay stable even when a new enemy type is added.
        self.world.collisions.register('player', 'item', self._on_player_item)
        self.world.collisions.register('player', 'portal', self._on_player_portal)
        self.world.collisions.register('player_projectile', 'enemy', self._on_projectile_enemy)
        self.world.collisions.register('player', 'terrain', self._on_player_terrain)
        self.world.commit()

        # The camera begins centered on the player in world space.
        self.camera.follow(self.player.x, self.player.y)
        self.set_notice(
            '좌우로 이동하면 카메라가 스크롤됩니다. 충돌은 월드 좌표로만 처리됩니다.',
            4.0,
        )

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            from src.scenes.main_menu_scene import MainMenuScene
            self.app.scene_manager.change(MainMenuScene)
            return

        if event.type == pygame.KEYDOWN and event.key == pygame.K_F5:
            self.app.reload_data()
            self.set_notice(
                'JSON 데이터테이블을 다시 읽었습니다. 새로 생성되는 객체부터 새 수치를 사용합니다.',
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

        # Update and collision: world coordinates only.
        self.world.update(delta_seconds, self.app)

        # Camera movement happens afterward and never changes entity x/y.
        if self.player is not None and self.player.alive:
            self.camera.follow(self.player.x, self.player.y)

        if self.app.timer.game_time > self._notice_until:
            self.notice = ''

    def draw(self, screen: pygame.Surface) -> None:
        if self.world is None or self.camera is None:
            return

        self._draw_world_grid(screen)
        self.world.draw(screen, self.app, self.camera)

        if self.player is not None:
            self.hud.draw(screen, self.app, self.player, self.camera, self.notice)

    def _draw_world_grid(self, screen: pygame.Surface) -> None:
        """Light world-space reference grid so scrolling is obvious in prototype."""

        if self.camera is None:
            return

        camera = self.camera
        bounds = camera.world_bounds
        line_color = (31, 37, 49)
        major_color = (44, 51, 66)
        label_color = (106, 120, 143)

        grid_step = 200
        start_x = int(camera.view_left // grid_step) * grid_step
        end_x = int(camera.view_right // grid_step + 1) * grid_step

        for world_x in range(start_x, end_x + 1, grid_step):
            if world_x < bounds.left or world_x > bounds.right:
                continue

            screen_x, _ = camera.world_to_screen(world_x, bounds.top)
            is_major = world_x % 1000 == 0
            pygame.draw.line(
                screen,
                major_color if is_major else line_color,
                (screen_x, 0),
                (screen_x, screen.get_height()),
                width=2 if is_major else 1,
            )

            if is_major:
                label = self.app.fonts.get(16).render(f'WORLD X {world_x}', True, label_color)
                screen.blit(label, (screen_x + 8, 188))

        grid_step_y = 200
        start_y = int(camera.view_top // grid_step_y) * grid_step_y
        end_y = int(camera.view_bottom // grid_step_y + 1) * grid_step_y

        for world_y in range(start_y, end_y + 1, grid_step_y):
            if world_y < bounds.top or world_y > bounds.bottom:
                continue

            _, screen_y = camera.world_to_screen(bounds.left, world_y)
            pygame.draw.line(
                screen,
                line_color,
                (0, screen_y),
                (screen.get_width(), screen_y),
                width=1,
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
                    self.player.x + self.player.facing * (self.player.width * 0.55),
                    self.player.y,
                    self.player.facing,
                )
            )
            self.set_notice(f"{skill['display_name']} 사용", 0.7)
        else:
            self.set_notice(f"{skill['display_name']}은(는) 아직 구현되지 않은 행동 유형입니다.", 2.0)

    def _on_player_item(self, player: Player, item: ItemDrop, world: World, app: GameApp) -> None:
        message = player.add_item(item.item_id, 1, item.definition)
        world.remove(item)
        self.set_notice(message, 2.0)

    def _on_player_portal(self, player: Player, portal: Portal, world: World, app: GameApp) -> None:
        self.set_notice(f"포탈 감지: 다음에는 '{portal.target_stage_id}' 로드 규칙을 연결합니다.", 1.0)

    def _on_projectile_enemy(
        self,
        projectile: Projectile,
        enemy: Enemy,
        world: World,
        app: GameApp,
    ) -> None:
        if projectile.register_enemy_hit(enemy, world) and enemy.take_damage(projectile.damage, app):
            self.set_notice(f"{enemy.display_name}에게 {projectile.damage} 피해", 0.6)

    @staticmethod
    def _on_player_terrain(player: Player, terrain: TerrainBlock, world: World, app: GameApp) -> None:
        # Intentional extension point: when gravity/jump are added, move the
        # resolution code to a PlayerMovementSystem rather than expanding Scene.
        _ = (player, terrain, world, app)

    def set_notice(self, message: str, seconds: float) -> None:
        self.notice = message
        self._notice_until = self.app.timer.game_time + seconds
