"""Application configuration loaded from environment variables."""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy.engine import URL

PROJECT_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(PROJECT_ROOT / ".env")


@dataclass(frozen=True, slots=True)
class Settings:
    app_env: str
    database_host: str
    database_port: int
    database_name: str
    database_user: str
    database_password: str

    @classmethod
    def from_environment(cls) -> "Settings":
        required = (
            "DATABASE_HOST",
            "DATABASE_PORT",
            "DATABASE_NAME",
            "DATABASE_USER",
            "DATABASE_PASSWORD",
        )
        missing = [key for key in required if not os.getenv(key)]

        if missing:
            raise RuntimeError(
                "Missing required environment variables: "
                + ", ".join(missing)
                + ". Configure them in the local .env file."
            )

        try:
            port = int(os.environ["DATABASE_PORT"])
        except ValueError as exc:
            raise RuntimeError("DATABASE_PORT must be an integer.") from exc

        if not 1 <= port <= 65535:
            raise RuntimeError("DATABASE_PORT must be between 1 and 65535.")

        return cls(
            app_env=os.getenv("APP_ENV", "development"),
            database_host=os.environ["DATABASE_HOST"],
            database_port=port,
            database_name=os.environ["DATABASE_NAME"],
            database_user=os.environ["DATABASE_USER"],
            database_password=os.environ["DATABASE_PASSWORD"],
        )

    @property
    def database_url(self) -> URL:
        """Build a safely escaped SQLAlchemy connection URL."""
        return URL.create(
            drivername="postgresql+psycopg",
            username=self.database_user,
            password=self.database_password,
            host=self.database_host,
            port=self.database_port,
            database=self.database_name,
        )


settings = Settings.from_environment()
