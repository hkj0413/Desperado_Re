from __future__ import annotations

from typing import TYPE_CHECKING

from src.gameplay.entities.enemy import Enemy
from src.gameplay.entities.item_drop import ItemDrop
from src.gameplay.entities.player import Player
from src.gameplay.party import PartyManager

if TYPE_CHECKING:
    from src.app import GameApp


def create_player(
    app: GameApp,
    party: PartyManager,
    x: float,
    y: float,
) -> Player:
    return Player(party, x, y)


def create_enemy(
    app: GameApp,
    enemy_id: str,
    x: float,
    y: float,
) -> Enemy:
    return Enemy(
        enemy_id,
        app.data.record('enemies', enemy_id),
        app.data.config()['enemy_shared'],
        x,
        y,
    )


def create_item_drop(
    app: GameApp,
    item_id: str,
    x: float,
    y: float,
) -> ItemDrop:
    return ItemDrop(
        item_id,
        app.data.record('items', item_id),
        x,
        y,
    )
