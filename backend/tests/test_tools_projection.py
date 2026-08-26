"""公开 TOOLS 投影回归测试。

保证 MCP 引入后聊天助手可见的工具 schema 与之前完全一致：
- 每个公开 TOOLS 条目的 keys 精确等于 {name, description, input_schema}
- 不含 read_only / annotations / inputSchema 等 MCP 专用字段
- 投影内容与注册表对应字段逐字段一致
- 与引入 MCP 前的 git 基线（HEAD 版本 tools.py 生成的 TOOLS）一致
"""

import json
import subprocess
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def test_public_tools_exact_keys():
    from app.chat.tools import TOOLS

    assert TOOLS, "TOOLS 不应为空"
    for entry in TOOLS:
        assert set(entry.keys()) == {"name", "description", "input_schema"}, (
            f"公开 TOOLS 条目 {entry.get('name')} 携带多余字段: {sorted(entry.keys())}"
        )
        assert "read_only" not in entry
        assert "annotations" not in entry
        assert "inputSchema" not in entry


def test_projection_matches_registry():
    from app.chat.tools import TOOL_REGISTRY, TOOLS

    by_name = {e["name"]: e for e in TOOLS}
    assert len(by_name) == len(TOOL_REGISTRY) == len(TOOLS)
    for reg in TOOL_REGISTRY:
        pub = by_name[reg["name"]]
        assert pub["description"] == reg.get("description", "")
        assert pub["input_schema"] == reg.get(
            "input_schema", {"type": "object", "properties": {}}
        )


def test_build_tools_list_matches_public_tools():
    from app.chat.session import build_tools_list
    from app.chat.tools import TOOLS

    assert build_tools_list() is TOOLS or build_tools_list() == TOOLS


def _baseline_tools_from_head():
    """从 git HEAD 取引入 MCP 前的 tools.py，加载其 TOOLS 作为基线。

    若不在 git 仓库或 HEAD 无该文件（理论不可能），跳过对比。
    """
    try:
        blob = subprocess.run(
            ["git", "show", "HEAD:backend/app/chat/tools.py"],
            capture_output=True, text=True, check=True, cwd=BACKEND_ROOT.parent,
        ).stdout
    except Exception:
        return None
    ns: dict = {}
    exec(compile(blob, "head_tools.py", "exec"), ns)  # noqa: S102 - 测试内受控执行
    return ns.get("TOOLS")


def test_public_tools_match_pre_mcp_baseline():
    baseline = _baseline_tools_from_head()
    if baseline is None:
        import pytest
        pytest.skip("无法读取 git HEAD 基线")
    from app.chat.tools import TOOLS

    assert TOOLS == baseline, (
        "公开 TOOLS 与引入 MCP 前的基线不一致 —— 聊天助手协议行为被改变"
    )


def test_openai_conversion_unaffected():
    from app.chat.tools import TOOLS, to_openai_tools

    converted = to_openai_tools(TOOLS)
    assert len(converted) == len(TOOLS)
    for c, t in zip(converted, TOOLS):
        assert c["function"]["name"] == t["name"]
        assert c["function"]["parameters"] == t["input_schema"]
