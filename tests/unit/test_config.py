import pytest

from inciflow.core.config import Settings


@pytest.fixture
def valid_environment(monkeypatch):
    values = {
        "DATABASE_HOST": "localhost",
        "DATABASE_PORT": "5432",
        "DATABASE_NAME": "test_db",
        "DATABASE_USER": "test_user",
        "DATABASE_PASSWORD": "test_password",
    }

    for key, value in values.items():
        monkeypatch.setenv(key, value)

    for key in (
        "APP_ENV",
        "GITHUB_TOKEN",
        "GITHUB_OWNER",
        "GITHUB_REPOSITORY",
        "GITHUB_SYNC_OVERLAP_SECONDS",
    ):
        monkeypatch.delenv(key, raising=False)


def test_settings_load_required_values_and_defaults(
    valid_environment,
):
    settings = Settings.from_environment()

    assert settings.app_env == "development"
    assert settings.database_host == "localhost"
    assert settings.database_port == 5432
    assert settings.database_name == "test_db"
    assert settings.database_user == "test_user"
    assert settings.database_password == "test_password"
    assert settings.github_token is None
    assert settings.github_owner is None
    assert settings.github_repository is None
    assert settings.github_sync_overlap_seconds == 120


def test_settings_load_optional_github_configuration(
    valid_environment,
    monkeypatch,
):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    monkeypatch.setenv("GITHUB_OWNER", "octo")
    monkeypatch.setenv("GITHUB_REPOSITORY", "widget")
    monkeypatch.setenv("GITHUB_SYNC_OVERLAP_SECONDS", "300")

    settings = Settings.from_environment()

    assert settings.app_env == "test"
    assert settings.github_token == "test-token"
    assert settings.github_owner == "octo"
    assert settings.github_repository == "widget"
    assert settings.github_sync_overlap_seconds == 300


@pytest.mark.parametrize(
    "missing_variable",
    [
        "DATABASE_HOST",
        "DATABASE_PORT",
        "DATABASE_NAME",
        "DATABASE_USER",
        "DATABASE_PASSWORD",
    ],
)
def test_settings_reject_missing_required_variables(
    valid_environment,
    monkeypatch,
    missing_variable,
):
    monkeypatch.delenv(missing_variable)

    with pytest.raises(
        RuntimeError,
        match="Missing required environment variables",
    ) as error:
        Settings.from_environment()

    assert missing_variable in str(error.value)


@pytest.mark.parametrize("port", ["abc", "5432.5"])
def test_settings_reject_non_integer_database_port(
    valid_environment,
    monkeypatch,
    port,
):
    monkeypatch.setenv("DATABASE_PORT", port)

    with pytest.raises(RuntimeError, match="DATABASE_PORT must be an integer"):
        Settings.from_environment()


@pytest.mark.parametrize("port", ["0", "65536", "-1"])
def test_settings_reject_database_port_out_of_range(
    valid_environment,
    monkeypatch,
    port,
):
    monkeypatch.setenv("DATABASE_PORT", port)

    with pytest.raises(
        RuntimeError,
        match="DATABASE_PORT must be between 1 and 65535",
    ):
        Settings.from_environment()


@pytest.mark.parametrize("overlap", ["abc", "1.5"])
def test_settings_reject_non_integer_overlap(
    valid_environment,
    monkeypatch,
    overlap,
):
    monkeypatch.setenv("GITHUB_SYNC_OVERLAP_SECONDS", overlap)

    with pytest.raises(
        RuntimeError,
        match="GITHUB_SYNC_OVERLAP_SECONDS must be an integer",
    ):
        Settings.from_environment()


def test_settings_reject_negative_overlap(
    valid_environment,
    monkeypatch,
):
    monkeypatch.setenv("GITHUB_SYNC_OVERLAP_SECONDS", "-1")

    with pytest.raises(
        RuntimeError,
        match="GITHUB_SYNC_OVERLAP_SECONDS must be non-negative",
    ):
        Settings.from_environment()


def test_database_url_escapes_credentials(valid_environment):
    settings = Settings.from_environment()
    settings = Settings(
        app_env=settings.app_env,
        database_host=settings.database_host,
        database_port=settings.database_port,
        database_name=settings.database_name,
        database_user="test@user",
        database_password="p@ss/word",
    )

    url = settings.database_url

    assert url.drivername == "postgresql+psycopg"
    assert url.username == "test@user"
    assert url.password == "p@ss/word"
    assert url.render_as_string(hide_password=False) == (
        "postgresql+psycopg://test%40user:p%40ss%2Fword"
        "@localhost:5432/test_db"
    )
