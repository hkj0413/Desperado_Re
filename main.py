from pathlib import Path

from src.app import GameApp


if __name__ == "__main__":
    project_root = Path(__file__).resolve().parent
    GameApp(project_root).run()
