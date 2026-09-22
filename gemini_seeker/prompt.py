"""工具桥接 prompt 构造。"""

SYSTEM_TEMPLATE = """You are a helpful assistant running behind a bridge that supports tool use.
You MUST respond with JSON only. Do not output markdown code fences.

Output schema (choose ONE):
- To call a tool:  {{"tool_calls": [{{"name": "<tool_name>", "arguments": {{...}}}}]}}
- To reply to the user:  {{"content": "<assistant_text>"}}

Available tools:
{tools}
"""


def build_tools_block(tools):
    lines = []
    for t in tools or []:
        fn = t.get("function", t) if isinstance(t, dict) else {}
        name = fn.get("name", "unknown")
        desc = (fn.get("description") or "").strip().replace("\n", " ")
        params = fn.get("parameters") or {}
        props = params.get("properties") or {}
        arg_names = ", ".join(props.keys()) if props else ""
        lines.append(f"- {name}: {desc}  (args: {arg_names})")
    return "\n".join(lines) if lines else "(no tools)"


def build_system_prompt(tools):
    return SYSTEM_TEMPLATE.format(tools=build_tools_block(tools))


def build_turn_prompt(system_prompt, recent_turns, user_text):
    parts = [system_prompt, ""]
    if recent_turns:
        parts.append("## Recent conversation")
        for role, text in recent_turns:
            parts.append(f"{role}: {text}")
        parts.append("")
    parts.append("## Current request")
    parts.append(user_text)
    return "\n".join(parts)
