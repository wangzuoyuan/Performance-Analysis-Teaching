import asyncio
import json

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.chat.config import get_chat_config
from app.chat.tools import create_anthropic_client, create_openai_client, to_openai_tools

router = APIRouter(prefix="/chat", tags=["chat"])
CHAT_MAX_TOKENS = 4096
CHAT_MAX_CONTINUATIONS = 2

SYSTEM_PROMPT = """你是一位任课老师的成绩分析助手。你只分析这位老师当前任教的一门学科（后端自动解析，无需也不能切换学科）。老师同时任教这门学科的多个「教学班」：高一教学班就是行政班（数字，如「1班」），高二/三可为走班教学班（如「物A1」「史B3」）。所有分析都围绕「当前任教学科 + 我教的教学班成员集合」进行。

核心规则：
1. 你只能回答当前任教学科的问题；不得讨论其他学科、不得汇总多门学科成绩
2. 引用任何数字必须先经过工具查询；不准凭空给数据
3. 用户问”最近两次/最近几次/多场考试谁进步最大或退步最大”时，调用 multi_exam_progress_ranking；用户说”最近两次”就传 recent_count=2，用户说”几次趋势”就按语义传 recent_count 和 min_points
4. 用户问某年级本学科进步最大/退步最大/提升最多时，调用 subject_progress_ranking
5. 用户问”这个同学/某学生整体情况/学习情况/优劣势/建议”时，调用 student_learning_profile；如果当前页面上下文有 student_id，就直接使用它
5.1 用户问高分段/临界段/薄弱段人数随时间/历次/最近几次的变化、走势、有没有增减时，调用 band_trend；只问某次考试的段位分布则用 focus_list。段位区间口径以下方"当前重点关注段位口径"为准
5.2 用户给出临时排名阈值或排名区间（如“班内前10名""排名5-15名之间”）并问人数、变化或趋势时，调用 custom_rank_band_trend
5.3 用户问某次考试本学科排名区间筛选名单（如“前10名有哪些”）时，调用 rank_range_filter。用户问多场考试排名频次/前20%次数时，调用 rank_frequency_stat
6. 描述成绩**趋势和进退步**时，严格按以下规则选择指标，**禁止用”分数从X升到Y””提升/下降Z分”来描述趋势走势**：
   - 高一单科：用年级百分位（grade_percentile）；百分位降低=进步，升高=退步
   - 高二/高三 语数英单科：用年级百分位（grade_percentile）
   - 高二/高三 选考单科：用等级分（grade_score）；不用原始分，不用百分位
   - raw_score 只允许出现在”该次考试原始分为X”的单点描述中，不得用于计算进退步幅度
   - 班内排名（subject_rank）用于单次考试段位判断和班内对比
7. 工具返回 available=false 或 raw_score/grade_score 均为空，表示未参考或无有效成绩；不得把残留百分位当作真实成绩
8. 涉及作业、缺交、欠交、完成情况时调用作业工具：单个学生用 student_homework_summary，全班缺交排行用 class_homework_ranking，要把缺交和成绩联系起来（如“缺交多是否成绩差”）用 homework_grade_correlation。重要口径：作业数据只记录缺交、请假、迟到等负面信号，不包含作业完成质量或评分，措辞上不要把“缺交少”等同于“作业认真/质量高”
9. 用户要“结合最近谈话/家访”“准备和某某的谈话提纲”“写给某某家长的沟通稿”时，调用 student_notes 读取该生成长/谈话档案，并结合 student_learning_profile（成绩）与 student_homework_summary（缺交）综合起草。谈话档案是班主任私密记录，措辞必须稳妥、尊重学生
10. 班级口径：老师任教多个教学班。用户没指定班时，默认统计「我教的所有教学班」成员；用户提到具体班级（“物A1班”“1班”“我教的班”等）时，先调用 list_my_classes 把班级名解析成 teaching_class_id，再传给相关工具的 teaching_class_id 参数（不要再传 class_num）。如果页面上下文已给出 scope_mode=teaching_class 和 teaching_class_id，且用户未明确提其他班，可直接使用该 teaching_class_id。回答里提到学生时，可附带其所属教学班标签。"""


def sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def build_tools_list():
    from app.chat.tools import TOOLS

    return TOOLS


def block_to_message_content(block) -> dict:
    if block.type == "text":
        return {"type": "text", "text": block.text}
    if block.type == "tool_use":
        return {"type": "tool_use", "id": block.id, "name": block.name, "input": block.input}
    return {}


def _band_config_line() -> str:
    """把用户自定义的段位口径拼成一行，注入系统提示，保证 AI 文字表述与页面/工具一致。"""
    try:
        from app.analysis.config import get_band_config

        c = get_band_config()
        return (
            "\n\n当前重点关注段位口径（按学籍排名，用户可自定义，引用时一律以此为准）："
            f"高分段 1-{c['high_score_max']}名、"
            f"临界段 {c['critical_min']}-{c['critical_max']}名、"
            f"薄弱段 第 {c['weak_min']} 名及以后。"
        )
    except Exception:
        return ""


def _safe_page(raw_page) -> str | None:
    """只允许 page 的 pathname（有限字符串），拒绝 href/query/object。

    安全约束（dict/string 同规则）：
    - 必须以 ``/`` 开头；
    - 长度 ≤ 200；
    - 不含 CR/LF/TAB/NUL 等控制字符；
    - 不含 ``?`` / ``#``（防 query/hash 注入）。
    """
    if raw_page is None:
        return None
    if isinstance(raw_page, dict):
        pathname = raw_page.get("pathname")
        if isinstance(pathname, str):
            return _safe_page(pathname)
        return None
    if not isinstance(raw_page, str):
        return None
    if len(raw_page) > 200:
        return None
    if not raw_page.startswith("/"):
        return None
    if any(ch in raw_page for ch in ("?", "#", "\r", "\n", "\t", "\x00")):
        return None
    # 拒绝其他 C0 控制字符
    if any(ord(ch) < 0x20 for ch in raw_page):
        return None
    return raw_page


def _safe_student_id(raw) -> str | None:
    """student_id 必须是有限短字符串，拒绝 object/超长/控制字符注入。

    拒绝全部 C0 控制字符（含 CR/LF/TAB/NUL 等），而非只拒绝 ``\\n``。
    """
    if not isinstance(raw, str):
        return None
    if len(raw) > 50:
        return None
    if any(ord(ch) < 0x20 for ch in raw):
        return None
    return raw


def _safe_exam_id(raw) -> int | None:
    """exam_id 必须是正整数（type(x) is int 拒绝 bool）。"""
    if type(raw) is int and raw > 0:
        return raw
    return None


def build_system_prompt(context: dict | None = None) -> str:
    prompt = SYSTEM_PROMPT + _band_config_line()

    if not context:
        return prompt

    # 安全上下文：每个字段都经过类型/范围校验，非法值直接丢弃。
    safe_context: dict = {}

    page = _safe_page(context.get("page"))
    if page is not None:
        safe_context["page"] = page

    sid = _safe_student_id(context.get("student_id"))
    if sid is not None:
        safe_context["student_id"] = sid

    eid = _safe_exam_id(context.get("exam_id"))
    if eid is not None:
        safe_context["exam_id"] = eid

    scope_mode = context.get("scope_mode")
    tc_id = context.get("teaching_class_id")
    if scope_mode in ("all", "teaching_class"):
        safe_context["scope_mode"] = scope_mode
    # type(x) is int rejects bool (isinstance(True, int) == True is a known Python pitfall)
    if type(tc_id) is int and tc_id > 0:
        safe_context["teaching_class_id"] = tc_id

    if not safe_context:
        return prompt

    return (
        prompt
        + "\n\n当前页面上下文（仅用于理解“这个学生/本次考试/当前班级”等指代，不能替代工具查询数字）："
        + json.dumps(safe_context, ensure_ascii=False)
    )


_SCOPE_TOOLS = frozenset(
    {
        "list_exams",
        "student_exam_detail",
        "student_trend",
        "student_learning_profile",
        "class_trend",
        "compare_classes",
        "focus_list",
        "subject_weakness",
        "subject_progress_ranking",
        "multi_exam_progress_ranking",
        "band_trend",
        "custom_rank_band_trend",
        "rank_range_filter",
        "rank_frequency_stat",
        "homework_grade_correlation",
        "student_lookup",
        "class_homework_ranking",
        "student_homework_summary",
        "student_notes",
    }
)


def _inject_page_scope(context: dict | None) -> dict | None:
    """从页面 context 提取 scope 信息，返回 {scope_mode, teaching_class_id} 或 None。

    纯函数：不查 DB，只看 context 中的 scope_mode / teaching_class_id。
    - scope_mode=all → {scope_mode: "all", teaching_class_id: None}
    - scope_mode=teaching_class + teaching_class_id=N(正整数) → {scope_mode: "teaching_class", teaching_class_id: N}
    - 只有 teaching_class_id(正整数) 没有 scope_mode → 自动识别为 teaching_class
    - teaching_class_id 非正整数/非法类型 → 视为 all 或丢弃
    - 无 scope 相关字段 → None（不注入）
    """
    if not context:
        return None

    scope_mode = context.get("scope_mode")
    raw_tc_id = context.get("teaching_class_id")
    # type(x) is int rejects bool; isinstance(True, int) == True is the pitfall
    tc_id = raw_tc_id if (type(raw_tc_id) is int and raw_tc_id > 0) else None

    if scope_mode == "all":
        return {"scope_mode": "all", "teaching_class_id": None}
    if scope_mode == "teaching_class":
        if tc_id is not None:
            return {"scope_mode": "teaching_class", "teaching_class_id": tc_id}
        return None
    if scope_mode is None and tc_id is not None:
        return {"scope_mode": "teaching_class", "teaching_class_id": tc_id}
    return None


def _apply_scope_to_tool_args(args: dict, page_scope: dict | None) -> dict:
    """把页面 scope 注入工具调用参数（仅限接受 teaching_class_id 的工具）。

    硬约束规则（具体班优先于模型自选）：
    - scope_mode=teaching_class → 页面 teaching_class_id 无条件覆盖模型值。
      用户当前页面锁定了某个教学班，模型不能自行改查别的班。
    - scope_mode=all → 模型自己传了 teaching_class_id 就保留（允许用户经工具
      选择具体合法班）；模型没传则注入 None（全部模式）。
    - 返回新的 args dict，不修改原 dict。
    """
    if not page_scope:
        return args
    result = dict(args)
    if page_scope.get("scope_mode") == "teaching_class":
        result["teaching_class_id"] = page_scope.get("teaching_class_id")
    else:  # all
        if "teaching_class_id" not in result or result.get("teaching_class_id") is None:
            result["teaching_class_id"] = page_scope.get("teaching_class_id")
    return result


def _anthropic_messages_to_openai(messages: list, system_prompt: str) -> list[dict]:
    """把 Anthropic 风格历史消息转成 OpenAI chat.completions 格式。"""
    out: list[dict] = [{"role": "system", "content": system_prompt}]
    for msg in messages:
        role = msg.get("role")
        content = msg.get("content")
        if isinstance(content, str):
            out.append({"role": role, "content": content})
            continue
        if not isinstance(content, list):
            continue
        if role == "assistant":
            text_parts = []
            tool_calls = []
            for block in content:
                btype = block.get("type")
                if btype == "text":
                    text_parts.append(block.get("text", ""))
                elif btype == "tool_use":
                    tool_calls.append(
                        {
                            "id": block.get("id"),
                            "type": "function",
                            "function": {
                                "name": block.get("name"),
                                "arguments": json.dumps(block.get("input") or {}, ensure_ascii=False),
                            },
                        }
                    )
            entry: dict = {"role": "assistant", "content": "".join(text_parts) or None}
            if tool_calls:
                entry["tool_calls"] = tool_calls
            out.append(entry)
        elif role == "user":
            text_parts = []
            tool_results = []
            for block in content:
                btype = block.get("type")
                if btype == "text":
                    text_parts.append(block.get("text", ""))
                elif btype == "tool_result":
                    tool_results.append(block)
            if text_parts:
                out.append({"role": "user", "content": "".join(text_parts)})
            for tr in tool_results:
                out.append(
                    {
                        "role": "tool",
                        "tool_call_id": tr.get("tool_use_id"),
                        "content": tr.get("content", ""),
                    }
                )
    return out


def _join_continuation(parts: list[str]) -> str:
    text = ""
    for part in parts:
        if not part:
            continue
        if text and not text.endswith(("\n", " ", "　")) and not part.startswith(("\n", " ", "，", "。", "；", "：", "、", "）", ")", "]")):
            text += "\n"
        text += part
    return text


def _continuation_prompt() -> str:
    return "请从上一句后继续完成回答，不要重复已经写过的内容；如果已经完整结束，只回复空内容。"


async def _stream_openai(config, messages: list, context: dict | None):
    from app.chat.tools import execute_tool

    client = create_openai_client(config)
    tools = to_openai_tools(build_tools_list())
    system_prompt = build_system_prompt(context)
    chat_messages = _anthropic_messages_to_openai(messages, system_prompt)
    page_scope = _inject_page_scope(context)

    for _ in range(8):
        try:
            response = client.chat.completions.create(
                model=config.model,
                messages=chat_messages,
                tools=tools,
                max_tokens=CHAT_MAX_TOKENS,
            )
        except Exception as exc:
            yield sse({"type": "text", "delta": f"对话接口调用失败：{exc}"})
            yield sse({"type": "done"})
            return

        choice = response.choices[0]
        msg = choice.message
        tool_calls = getattr(msg, "tool_calls", None) or []

        if tool_calls:
            assistant_entry: dict = {
                "role": "assistant",
                "content": msg.content or None,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments or "{}",
                        },
                    }
                    for tc in tool_calls
                ],
            }
            chat_messages.append(assistant_entry)
            for tc in tool_calls:
                try:
                    raw_args = json.loads(tc.function.arguments or "{}")
                except Exception:
                    raw_args = {}
                if tc.function.name in _SCOPE_TOOLS:
                    args = _apply_scope_to_tool_args(raw_args, page_scope)
                else:
                    args = raw_args
                yield sse({"type": "tool_call", "name": tc.function.name, "input": args})
                try:
                    result = execute_tool(tc.function.name, args)
                except Exception as exc:
                    result = {"error": str(exc)}
                chat_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )
            continue

        text_parts = [msg.content or ""]
        finish_reason = getattr(choice, "finish_reason", None)
        for _ in range(CHAT_MAX_CONTINUATIONS):
            if finish_reason != "length" or not text_parts[-1]:
                break
            chat_messages.append({"role": "assistant", "content": text_parts[-1]})
            chat_messages.append({"role": "user", "content": _continuation_prompt()})
            try:
                continuation = client.chat.completions.create(
                    model=config.model,
                    messages=chat_messages,
                    max_tokens=CHAT_MAX_TOKENS,
                )
            except Exception:
                break
            continuation_choice = continuation.choices[0]
            continuation_text = continuation_choice.message.content or ""
            if not continuation_text:
                break
            text_parts.append(continuation_text)
            finish_reason = getattr(continuation_choice, "finish_reason", None)

        text = _join_continuation(text_parts)
        if finish_reason == "length":
            text += "\n\n（回答仍达到长度上限，已尽量保留完整内容；如需更长明细请继续追问。）"
        if text:
            yield sse({"type": "text", "delta": text})
        yield sse({"type": "done"})
        return

    yield sse({"type": "text", "delta": "工具调用轮次过多，已停止。请缩小问题范围后重试。"})
    yield sse({"type": "done"})


async def stream_chat(messages: list, context: dict | None = None):
    """SSE 对话。支持 Claude / OpenAI 兼容接口 tool-use，并把工具调用元数据推给前端。"""
    config = get_chat_config()
    if not config.is_configured:
        key_name = "OPENAI_API_KEY" if config.provider == "openai" else "ANTHROPIC_API_KEY"
        yield sse({"type": "text", "delta": f"未设置有效的 {key_name}，对话助手暂不可用。"})
        yield sse({"type": "done"})
        return

    if config.provider == "openai":
        async for chunk in _stream_openai(config, messages, context):
            yield chunk
        return

    from app.chat.tools import execute_tool

    client = create_anthropic_client(config)
    tools = build_tools_list()
    chat_messages = list(messages)
    page_scope = _inject_page_scope(context)

    for _ in range(8):
        # MiniMax 等兼容端点偶发瞬时错误（401/429/5xx/网络抖动），读操作可安全重试
        response = None
        last_exc = None
        for attempt in range(3):
            try:
                response = client.messages.create(
                    model=config.model,
                    max_tokens=CHAT_MAX_TOKENS,
                    system=build_system_prompt(context),
                    messages=chat_messages,
                    tools=tools,
                )
                break
            except Exception as exc:
                last_exc = exc
                if attempt < 2:
                    await asyncio.sleep(0.6 * (attempt + 1))
        if response is None:
            yield sse({"type": "text", "delta": f"对话接口调用失败（已重试）：{last_exc}"})
            yield sse({"type": "done"})
            return

        tool_results = []
        assistant_content = []
        final_text_parts = []

        for block in response.content:
            if block.type == "text":
                assistant_content.append(block_to_message_content(block))
                final_text_parts.append(block.text)
            elif block.type == "tool_use":
                assistant_content.append(block_to_message_content(block))
                raw_args = block.input or {}
                if block.name in _SCOPE_TOOLS:
                    args = _apply_scope_to_tool_args(raw_args, page_scope)
                else:
                    args = raw_args
                yield sse({"type": "tool_call", "name": block.name, "input": args})
                try:
                    result = execute_tool(block.name, args)
                except Exception as exc:
                    result = {"error": str(exc)}
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )

        if tool_results:
            chat_messages.append({"role": "assistant", "content": assistant_content})
            chat_messages.append({"role": "user", "content": tool_results})
            continue

        text_parts = ["".join(final_text_parts)]
        stop_reason = getattr(response, "stop_reason", None)
        for _ in range(CHAT_MAX_CONTINUATIONS):
            if stop_reason != "max_tokens" or not text_parts[-1]:
                break
            chat_messages.append({"role": "assistant", "content": [{"type": "text", "text": text_parts[-1]}]})
            chat_messages.append({"role": "user", "content": _continuation_prompt()})

            continuation = None
            last_exc = None
            for attempt in range(3):
                try:
                    continuation = client.messages.create(
                        model=config.model,
                        max_tokens=CHAT_MAX_TOKENS,
                        system=build_system_prompt(context),
                        messages=chat_messages,
                    )
                    break
                except Exception as exc:
                    last_exc = exc
                    if attempt < 2:
                        await asyncio.sleep(0.6 * (attempt + 1))
            if continuation is None:
                text_parts.append(f"\n\n（继续生成失败：{last_exc}）")
                break

            continuation_text = "".join(
                block.text for block in continuation.content if block.type == "text"
            )
            if not continuation_text:
                break
            text_parts.append(continuation_text)
            stop_reason = getattr(continuation, "stop_reason", None)

        text = _join_continuation(text_parts)
        if stop_reason == "max_tokens":
            text += "\n\n（回答仍达到长度上限，已尽量保留完整内容；如需更长明细请继续追问。）"
        if text:
            yield sse({"type": "text", "delta": text})
        yield sse({"type": "done"})
        return

    yield sse({"type": "text", "delta": "工具调用轮次过多，已停止。请缩小问题范围后重试。"})
    yield sse({"type": "done"})


@router.post("")
async def chat(request: Request):
    body = await request.json()
    messages = body.get("messages", [])
    context = body.get("context", {})

    return StreamingResponse(
        stream_chat(messages, context),
        media_type="text/event-stream",
    )


@router.get("/config")
async def chat_config():
    config = get_chat_config()
    return {
        "provider": config.provider,
        "model": config.model,
        "configured": config.is_configured,
        "base_url_configured": bool(config.base_url),
    }
