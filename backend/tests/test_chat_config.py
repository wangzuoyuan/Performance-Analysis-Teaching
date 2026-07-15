from pathlib import Path

from app.chat.config import DEFAULT_MODEL, get_chat_config
from app.chat.session import block_to_message_content, build_system_prompt


def test_chat_config_reads_dotenv_file(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "ANTHROPIC_API_KEY=test-key",
                "ANTHROPIC_BASE_URL=https://example.com/api",
                "ANTHROPIC_MODEL=compatible-model",
            ]
        ),
        encoding="utf-8",
    )

    config = get_chat_config(env_file)

    assert config.api_key == "test-key"
    assert config.base_url == "https://example.com/api"
    assert config.model == "compatible-model"
    assert config.is_configured


def test_chat_config_dotenv_file_overrides_env_vars(tmp_path: Path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("ANTHROPIC_API_KEY=file-key\nANTHROPIC_MODEL=file-model\n", encoding="utf-8")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "env-key")
    monkeypatch.setenv("ANTHROPIC_MODEL", "env-model")

    config = get_chat_config(env_file)

    assert config.api_key == "file-key"
    assert config.model == "file-model"


def test_chat_config_reads_env_vars_when_dotenv_missing(tmp_path: Path, monkeypatch):
    env_file = tmp_path / ".env"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "env-key")
    monkeypatch.setenv("ANTHROPIC_MODEL", "env-model")

    config = get_chat_config(env_file)

    assert config.api_key == "env-key"
    assert config.model == "env-model"


def test_chat_config_placeholder_key_is_not_configured(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("ANTHROPIC_API_KEY=your_api_key_here\n", encoding="utf-8")

    config = get_chat_config(env_file)

    assert not config.is_configured
    assert config.model == DEFAULT_MODEL


def test_chat_ignores_non_display_content_blocks():
    class Block:
        type = "thinking"

    assert block_to_message_content(Block()) == {}


def test_system_prompt_includes_page_context():
    prompt = build_system_prompt({"student_id": "7240115", "page": {"pathname": "/student/7240115"}})

    assert "当前页面上下文" in prompt
    assert "7240115" in prompt


def test_system_prompt_single_subject_mouth():
    """单学科化后，系统提示词必须明确说明围绕任教学科，不得出现多学科禁词。"""
    prompt = build_system_prompt()

    assert "任教学科" in prompt
    for phrase in ["总分", "主三门", "五门", "九门", "+3", "3+3", "全年级"]:
        assert phrase not in prompt, f"系统提示词中不应出现「{phrase}」"


def test_system_prompt_whitelist_only_known_fields():
    """build_system_prompt 只允许白名单字段，未知字段丢弃。"""
    prompt = build_system_prompt({
        "student_id": "12345",
        "teaching_class_id": 7,
        "scope_mode": "teaching_class",
        "rogue_field": "INJECT_ME",
    })

    assert "12345" in prompt
    assert "teaching_class" in prompt
    assert "INJECT_ME" not in prompt
