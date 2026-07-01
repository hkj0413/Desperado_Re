from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pygame

if TYPE_CHECKING:
    from src.core.data_repository import DataRepository


class AudioManager:
    """Separates BGM, effects, and a single exclusive voice channel.

    - BGM uses pygame.mixer.music and can continue independently.
    - Effects use channels 1..15 and can overlap each other.
    - Voice uses channel 0 only. A new voice request is ignored while that
      channel is already playing; it never interrupts or queues another voice.
    """

    _VOICE_CHANNEL_INDEX = 0
    _EFFECT_CHANNEL_START = 1
    _CHANNEL_COUNT = 16

    def __init__(
        self,
        project_root: Path,
        data: DataRepository,
    ) -> None:
        self._project_root = project_root
        self._data = data
        self._available = False
        self._voice_channel: pygame.mixer.Channel | None = None
        self._effect_channels: list[pygame.mixer.Channel] = []
        self._sound_cache: dict[str, pygame.mixer.Sound] = {}

        try:
            if pygame.mixer.get_init() is None:
                pygame.mixer.init()

            pygame.mixer.set_num_channels(self._CHANNEL_COUNT)
            self._voice_channel = pygame.mixer.Channel(
                self._VOICE_CHANNEL_INDEX
            )
            self._effect_channels = [
                pygame.mixer.Channel(index)
                for index in range(
                    self._EFFECT_CHANNEL_START,
                    self._CHANNEL_COUNT,
                )
            ]
            self._available = True

        except pygame.error:
            # Missing sound hardware should not stop the game from launching.
            self._available = False

    def clear_cache(self) -> None:
        """Use after F5 data reload so changed sound paths are re-read."""
        self._sound_cache.clear()

    def play_effect(self, sound_id: str) -> bool:
        """Play a normal effect without touching BGM or the voice channel."""
        definition = self._get_definition(sound_id, expected_category='effect')
        if definition is None:
            return False

        sound = self._load_sound(sound_id, definition)
        if sound is None:
            return False

        channel = next(
            (item for item in self._effect_channels if not item.get_busy()),
            None,
        )
        if channel is None:
            return False

        channel.set_volume(float(definition['volume']))
        channel.play(sound)
        return True

    def play_voice(self, sound_id: str) -> bool:
        """Play a voice only when no other voice is currently playing.

        A busy voice channel causes the new request to be ignored. This is
        intentionally different from normal effects and BGM.
        """
        definition = self._get_definition(sound_id, expected_category='voice')
        if definition is None or self._voice_channel is None:
            return False

        if self._voice_channel.get_busy():
            return False

        sound = self._load_sound(sound_id, definition)
        if sound is None:
            return False

        self._voice_channel.set_volume(float(definition['volume']))
        self._voice_channel.play(sound)
        return True

    def play_bgm(self, sound_id: str, *, loop: bool = True) -> bool:
        """Play BGM through pygame's separate music stream."""
        definition = self._get_definition(sound_id, expected_category='bgm')
        if definition is None or not self._available:
            return False

        path = self._project_root / str(definition['path'])
        if not path.is_file():
            return False

        try:
            pygame.mixer.music.load(str(path))
            pygame.mixer.music.set_volume(float(definition['volume']))
            pygame.mixer.music.play(-1 if loop else 0)
        except pygame.error:
            return False

        return True

    def stop_bgm(self) -> None:
        if self._available:
            pygame.mixer.music.stop()

    def _get_definition(
        self,
        sound_id: str,
        *,
        expected_category: str,
    ) -> dict[str, object] | None:
        if not self._available:
            return None

        try:
            definition = self._data.record('sounds', sound_id)
        except Exception:
            return None

        if definition.get('category') != expected_category:
            return None

        return definition

    def _load_sound(
        self,
        sound_id: str,
        definition: dict[str, object],
    ) -> pygame.mixer.Sound | None:
        if sound_id in self._sound_cache:
            return self._sound_cache[sound_id]

        path = self._project_root / str(definition['path'])
        if not path.is_file():
            return None

        try:
            sound = pygame.mixer.Sound(str(path))
        except pygame.error:
            return None

        self._sound_cache[sound_id] = sound
        return sound
