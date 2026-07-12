import os

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

class Settings:
    PROJECT_NAME: str = "VibeScholar"
    SECRET_KEY: str = os.getenv("SECRET_KEY", "2134763u46827163484wudyg3468r4")
    # Resolves DB path relative to project root so it works for any user
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        f"sqlite:///{os.path.join(_project_root, 'vibescholar.db')}"
    )
    USE_MOCK: bool = os.getenv("USE_MOCK", "True").lower() == "true"

settings = Settings()
