"""Basic tests for configuration defaults."""
from backend.app.core.config import Settings


def test_settings_defaults() -> None:
    settings = Settings()
    assert settings.app_name == "graph-mem-chat-backend"
    assert settings.ollama_model == "gpt-oss-20b"
