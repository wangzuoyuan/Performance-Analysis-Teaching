"""只读 MCP 服务端（Streamable HTTP，stateless JSON，挂载 /mcp）。

作为现有 FastAPI 应用的子挂载运行，供笔记本上的 Hermes 等 MCP 客户端
经公网 HTTPS 调用。设计约束：

- 单一注册源：tools/list 由 chat/tools.py 的 TOOL_REGISTRY 中带
  read_only=True 元数据的条目派生；tools/call 一律经 execute_tool()
  分发。本模块不 import 数据库模型、不拼 SQL、不复制业务查询。
- 只读目录语义：未显式标记 read_only 的工具（含未来新增写入/删除工具）
  既不出现在 MCP 目录中，也无法通过 MCP 调用。
- 不污染聊天助手：MCP 元数据只存在于注册表；公开 TOOLS 是投影，
  发往 Anthropic/OpenAI 的 schema 与引入 MCP 前完全一致。
- 认证：独立 Bearer Token（MCP_BEARER_TOKEN），hmac 恒定时间比较，
  401 带 WWW-Authenticate: Bearer。token 只从环境变量读取，绝不写日志。
- 传输防护：保留 SDK 的 DNS rebinding / Host / Origin 校验，经
  MCP_ALLOWED_HOSTS / MCP_ALLOWED_ORIGINS 配置（缺省 localhost）。
  非浏览器客户端（Hermes）不带 Origin 头，SDK 语义是放行。
- 公网使用必须 HTTPS：Bearer Token 明文传输只有 TLS 边界保护。

环境变量：
- MCP_ENABLED：默认 false。false 时本模块不被挂载，应用完全不受影响。
- MCP_BEARER_TOKEN：启用时必填；空白/弱占位符/短于 32 字符 → 启动失败。
- MCP_ALLOWED_HOSTS / MCP_ALLOWED_ORIGINS：逗号分隔；缺省 localhost 系列。
"""

from __future__ import annotations

import hmac
import json
import logging
import os
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp

logger = logging.getLogger(__name__)

MCP_MOUNT_PATH = "/mcp"

# 启用 MCP 时拒绝这些明显是占位符的 token（防止照抄示例导致裸奔）。
_WEAK_TOKEN_PLACEHOLDERS = frozenset({
    "changeme", "change-me", "your_token_here", "your-token-here",
    "yourtoken", "secret", "token", "test", "mcp", "password",
    "123456", "12345678", "1234567890",
    "abcdef", "abcdefg", "abcdefgh", "0123456789", "aaaaaaaaaa",
})


class MCPConfigError(RuntimeError):
    """MCP 配置非法（启用但 token 缺失/弱等）。启动时抛出，fail closed。"""


def mcp_enabled() -> bool:
    return os.environ.get("MCP_ENABLED", "").strip().lower() in ("1", "true", "yes", "on")


def load_bearer_token() -> str:
    """读取并校验 MCP_BEARER_TOKEN；非法配置抛 MCPConfigError。"""
    token = os.environ.get("MCP_BEARER_TOKEN", "").strip()
    if not token:
        raise MCPConfigError(
            "MCP_ENABLED 已开启，但 MCP_BEARER_TOKEN 缺失或为空白；"
            "拒绝以无认证状态启动。请设置强随机 token（见 DEPLOY.md）。"
        )
    if token.lower() in _WEAK_TOKEN_PLACEHOLDERS:
        raise MCPConfigError(
            "MCP_BEARER_TOKEN 是弱占位符；拒绝以弱 token 启动。"
            "请用 openssl rand -hex 32 生成强随机 token。"
        )
    if len(token) < 32:
        raise MCPConfigError(
            "MCP_BEARER_TOKEN 长度不足 32 字符；拒绝以弱 token 启动。"
            "请用 openssl rand -hex 32 生成强随机 token。"
        )
    return token


def _split_env_list(name: str) -> list[str]:
    raw = os.environ.get(name, "")
    return [item.strip() for item in raw.split(",") if item.strip()]


def load_allowed_hosts() -> list[str]:
    """Host 头白名单。缺省 localhost；公网部署必须显式加域名（见 DEPLOY.md）。"""
    configured = _split_env_list("MCP_ALLOWED_HOSTS")
    if configured:
        return configured
    return ["localhost", "127.0.0.1", "[::1]",
            "localhost:*", "127.0.0.1:*", "[::1]:*"]


def load_allowed_origins() -> list[str]:
    """Origin 白名单。缺省 localhost。无 Origin 的非浏览器客户端放行（SDK 语义）。"""
    configured = _split_env_list("MCP_ALLOWED_ORIGINS")
    if configured:
        return configured
    return ["http://localhost", "http://127.0.0.1", "http://[::1]",
            "http://localhost:*", "http://127.0.0.1:*", "http://[::1]:*"]


def _unauthorized() -> JSONResponse:
    # 绝不把 token 或其任何部分放进响应。
    return JSONResponse(
        {"error": "unauthorized", "error_description": "Missing or invalid bearer token"},
        status_code=401,
        headers={"WWW-Authenticate": 'Bearer realm="mcp"'},
    )


class BearerAuthMiddleware:
    """纯 ASGI Bearer 认证中间件：覆盖挂载点内全部路径与方法。

    恒定时间比较；缺失/格式错误/不匹配一律 401。认证先于 SDK 的
    Host/Origin 校验与协议处理，未认证请求不会触达任何工具逻辑。
    """

    def __init__(self, app: ASGIApp, token: str) -> None:
        self.app = app
        self.token = token.encode("utf-8")

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request = Request(scope)
        header = request.headers.get("authorization", "")
        scheme, _, value = header.partition(" ")
        if scheme.lower() != "bearer" or not hmac.compare_digest(
            value.strip().encode("utf-8"), self.token
        ):
            logger.warning("MCP request rejected: invalid or missing bearer token")
            await _unauthorized()(scope, receive, send)
            return
        await self.app(scope, receive, send)


# ────────────────────── 只读目录（由单一注册源派生） ──────────────────────

REQUIRED_READONLY_TOOLS: tuple[str, ...] = (
    "list_my_classes",
    "list_exams",
    "student_lookup",
    "student_exam_detail",
    "student_trend",
    "student_learning_profile",
    "class_trend",
    "multi_exam_progress_ranking",
    "focus_list",
    "student_homework_summary",
    "student_notes",
)


def mcp_tool_catalog() -> list[dict[str, Any]]:
    """MCP 工具目录：TOOL_REGISTRY 中 read_only 条目的 MCP 形状视图。

    description / input_schema 原样沿用注册表，不改写。每次调用都重新
    读取注册表，因此注册表变化（含测试 monkeypatch）即时生效。
    """
    from mcp.types import ToolAnnotations

    from app.chat.tools import readonly_tool_catalog

    return [
        {
            "name": entry["name"],
            "description": entry.get("description", ""),
            "inputSchema": entry.get("input_schema", {"type": "object", "properties": {}}),
            "annotations": ToolAnnotations(
                read_only_hint=True,
                destructive_hint=False,
                idempotent_hint=True,
                open_world_hint=False,
            ),
        }
        for entry in readonly_tool_catalog()
    ]


def validate_required_tools() -> None:
    """确保用户指定必须暴露的 11 个只读工具都在目录中（防止注册表意外回退）。"""
    names = {t["name"] for t in mcp_tool_catalog()}
    missing = [n for n in REQUIRED_READONLY_TOOLS if n not in names]
    if missing:
        raise MCPConfigError(
            "MCP 工具目录缺少必须暴露的只读工具: " + ", ".join(missing)
        )


def build_mcp_server():
    """构建 low-level MCP Server（list/call 均走注册表与 execute_tool）。"""
    from mcp.server import Server
    from mcp.types import (
        CallToolRequestParams,
        CallToolResult,
        ListToolsResult,
        TextContent,
        Tool,
    )

    from app.chat import tools as chat_tools

    async def list_tools(ctx, params):
        tools = [
            Tool(
                name=t["name"],
                description=t["description"],
                input_schema=t["inputSchema"],
                annotations=t["annotations"],
            )
            for t in mcp_tool_catalog()
        ]
        return ListToolsResult(tools=tools)

    async def call_tool(ctx, params: CallToolRequestParams) -> CallToolResult:
        allowed = {t["name"] for t in mcp_tool_catalog()}
        if params.name not in allowed:
            # 未列入只读目录的工具一律不可经 MCP 调用（含未来新增写工具）。
            return CallToolResult(
                content=[TextContent(
                    type="text",
                    text=json.dumps(
                        {"error": "未知或不可经 MCP 调用的工具: " + params.name},
                        ensure_ascii=False,
                    ),
                )],
                is_error=True,
            )
        # 参数原样透传给 execute_tool —— MCP 层不改写、不过滤。
        args = dict(params.arguments or {})
        result = chat_tools.execute_tool(params.name, args)
        if isinstance(result, (str, int, float, bool)):
            text = json.dumps({"result": result}, ensure_ascii=False, default=str)
        else:
            text = json.dumps(result, ensure_ascii=False, default=str)
        return CallToolResult(content=[TextContent(type="text", text=text)])

    return Server(
        "grade-tracker-mcp",
        version="1.0.0",
        on_list_tools=list_tools,
        on_call_tool=call_tool,
    )


class MCPMount:
    """挂载结果：ASGI 子应用 + 需要宿主 lifespan 管理的 session manager。"""

    def __init__(self, app: ASGIApp, server) -> None:
        self.app = app
        self.server = server

    def session_manager(self):
        # streamable_http_app() 调用后 server.session_manager 才存在
        return self.server.session_manager


def mount_mcp() -> MCPMount:
    """构建完整 MCP 挂载（认证 + 传输防护 + 只读目录校验）。

    任何配置错误（token 缺失/弱、必须工具缺失）在此抛出，应用启动失败。
    """
    from mcp.server.transport_security import TransportSecuritySettings

    token = load_bearer_token()
    validate_required_tools()
    server = build_mcp_server()
    security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=load_allowed_hosts(),
        allowed_origins=load_allowed_origins(),
    )
    inner = server.streamable_http_app(
        streamable_http_path="/",   # 挂载前缀即完整路径 /mcp
        json_response=True,        # 每个 POST 回单个 JSON（客户端友好）
        stateless_http=True,       # 无会话；不落任何会话状态
        transport_security=security,
    )
    return MCPMount(BearerAuthMiddleware(inner, token), server)

