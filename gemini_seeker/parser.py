import random
import json
import re
def normalize_tool_call(tool_data_or_name, args_if_name=None):
    if isinstance(tool_data_or_name, str):
        name = tool_data_or_name
        args = args_if_name if args_if_name is not None else {}
    elif isinstance(tool_data_or_name, dict):
        tool_data = tool_data_or_name
        if "function" in tool_data and isinstance(tool_data["function"], dict):
            fn = tool_data["function"]
            name = fn.get("name") or tool_data.get("name")
            args = fn.get("arguments") or fn.get("parameters") or fn.get("input") or fn.get("args") or fn.get("params") or {}
        else:
            name = tool_data.get("name") or tool_data.get("tool") or tool_data.get("tool_name") or tool_data.get("function") or tool_data.get("action")
            args = tool_data.get("arguments") or tool_data.get("parameters") or tool_data.get("input") or tool_data.get("args") or tool_data.get("params") or tool_data.get("tool_input") or tool_data.get("action_input") or {}
    else:
        return None

    if not name or not isinstance(name, str):
        return None
    if isinstance(args, (dict, list)):
        args_str = json.dumps(args)
    elif isinstance(args, str):
        args_str = args
        try:
            json.loads(args_str)
        except Exception:
            args_str = json.dumps(args_str)
    else:
        args_str = json.dumps({})
    call_id = "call_" + "".join(random.choices(string.ascii_letters + string.digits, k=8))
    return {
        "id": call_id,
        "type": "function",
        "function": {
            "name": name.strip(),
            "arguments": args_str,
        },
    }


def clean_json_str(s):
    s = s.strip()
    if s.startswith("```json"):
        s = s[7:]
    elif s.startswith("```"):
        s = s[3:]
    if s.endswith("```"):
        s = s[:-3]
    return s.strip()


def _code_fence_spans(text):
    """Return the (start, end) spans of markdown fenced code blocks.

    Tool-call markup inside a fence is documentation/example text, not an
    actual tool call, so matches falling inside these spans are ignored.
    Unclosed fences extend to end-of-text.
    """
    return [(m.start(), m.end()) for m in re.finditer(r"```.*?(?:```|$)", text, re.DOTALL)]


def parse_tools(text):
    tools = []
    clean_text = text
    fence_spans = _code_fence_spans(text)

    def fenced(pos):
        return any(s <= pos < e for s, e in fence_spans)

    param_names = {"command", "description", "file_path", "content", "path", "prompt", "query", "subject", "old_string", "new_string", "url", "input"}
    tool_matches = list(re.finditer(r"<[｜\|]{0,2}(?:DSML[｜\|]{0,2})?\s*(?:tool_call|invoke|function_call)\s+(?:name|tool)=[\x27\x22]([^\x27\x22]+)[\x27\x22][^>]*>", text, re.IGNORECASE))
    real_tool_matches = [tm for tm in tool_matches if not fenced(tm.start())]

    if real_tool_matches:
        for i, tm in enumerate(real_tool_matches):
            candidate_name = tm.group(1).strip()
            start_idx = tm.end()
            end_idx = real_tool_matches[i+1].start() if i + 1 < len(real_tool_matches) else len(text)
            body = text[start_idx:end_idx]
            args = {}
            p_matches = re.finditer(r"<[｜\|]{0,2}(?:DSML[｜\|]{0,2})?\s*(?:parameter|tool_call|param|invoke)\s+name=[\x27\x22]([^\x27\x22]+)[\x27\x22][^>]*>(.*?)(?:</[｜\|]{0,2}(?:DSML[｜\|]{0,2})?\s*(?:parameter|tool_call|param|invoke)>|(?=<[｜\|]{0,2}(?:DSML[｜\|]{0,2})?\s*(?:parameter|tool_call|param|invoke)\s+name=)|$)", body, flags=re.DOTALL | re.IGNORECASE)
            for pm in p_matches:
                p_name = pm.group(1).strip()
                p_val = pm.group(2).strip()
                p_val = re.sub(r"</?(?:tool_calls?|invoke|function_call|parameter|param)\b[^>]*>", "", p_val, flags=re.IGNORECASE).strip()
                try:
                    args[p_name] = json.loads(p_val)
                except Exception:
                    args[p_name] = p_val
            tag_param_matches = re.finditer(r"<([A-Za-z0-9_\-]+)>(.*?)(?:</\1>|$)", body, flags=re.DOTALL | re.IGNORECASE)
            for pm in tag_param_matches:
                t_name = pm.group(1).strip().lower()
                if t_name in param_names:
                    t_val = pm.group(2).strip()
                    t_val = re.sub(r"</?(?:tool_calls?|invoke|function_call|parameter|param)\b[^>]*>", "", t_val, flags=re.IGNORECASE).strip()
                    try:
                        args[t_name] = json.loads(t_val)
                    except Exception:
                        args[t_name] = t_val
            if candidate_name:
                norm = normalize_tool_call(candidate_name, args)
                if norm:
                    tools.append(norm)

    if tools:
        clean_text = re.sub(r"<[｜\|]{0,2}(?:DSML[｜\|]{0,2})?\s*(?:tool_calls?|calls)[^>]*>.*?(?:</[｜\|]{0,2}(?:DSML[｜\|]{0,2})?\s*(?:tool_calls?|calls)>|$)", "", clean_text, flags=re.DOTALL | re.IGNORECASE).strip()
        clean_text = re.sub(r"<[｜\|]{0,2}(?:DSML[｜\|]{0,2})?\s*(?:invoke|function_call)[^>]*>.*?(?:</[｜\|]{0,2}(?:DSML[｜\|]{0,2})?\s*(?:invoke|function_call)>|$)", "", clean_text, flags=re.DOTALL | re.IGNORECASE).strip()

    if not tools and "DSML" in text:
        dsml_block_pattern = re.compile(r"<[｜\|]{2}DSML[｜\|]{2}([A-Za-z0-9_]+)>(.*?)(?:</[｜\|]{2}DSML[｜\|]{2}\1>|$)", re.DOTALL | re.IGNORECASE)
        param_pattern_b = re.compile(r"<[｜\|]{2}DSML[｜\|]{2}B([A-Za-z0-9_]+)[^>]*>(.*?)(?:</[｜\|]{2}DSML[｜\|]{2}B.*?>|$)", re.DOTALL | re.IGNORECASE)
        for m in dsml_block_pattern.finditer(text):
            if fenced(m.start()):
                continue
            tool_name = m.group(1).strip()
            body = m.group(2)
            args = {}
            for pm in param_pattern_b.finditer(body):
                p_name = pm.group(1).lower().strip()
                p_val = pm.group(2).strip()
                try:
                    args[p_name] = json.loads(p_val)
                except Exception:
                    args[p_name] = p_val
            norm = normalize_tool_call(tool_name, args)
            if norm:
                tools.append(norm)
        if not tools:
            tool_match = re.search(r"[｜\|]{2}DSML[｜\|]{2}(Bash|Read|Write|Edit|Agent|TaskList|TaskCreate|WebSearch|[A-Za-z0-9_]+)", text, re.IGNORECASE)
            if tool_match and not fenced(tool_match.start()):
                candidate = tool_match.group(1).strip()
                tool_name = "Bash" if candidate.lower().startswith("b") and candidate.lower() not in ["bdescription", "bparam"] else candidate
                args = {}
                cmd_match = re.search(r"[｜\|]{2}B[\x22\x27]?command[\x22\x27]?[^>]*>(.*?)(?:</[｜\|]{2}B|$)", text, re.DOTALL | re.IGNORECASE)
                desc_match = re.search(r"[｜\|]{2}B[\x22\x27]?description[\x22\x27]?[^>]*>(.*?)(?:</[｜\|]{2}B|$)", text, re.DOTALL | re.IGNORECASE)
                if cmd_match:
                    clean_cmd = re.sub(r"</?[｜\|]{2}DSML[｜\|]{2}[^>]*>", "", cmd_match.group(1)).strip("\x22\x27() ")
                    args["command"] = clean_cmd
                if desc_match:
                    clean_desc = re.sub(r"</?[｜\|]{2}DSML[｜\|]{2}[^>]*>", "", desc_match.group(1)).strip("\x22\x27() ")
                    args["description"] = clean_desc
                norm = normalize_tool_call(tool_name, args)
                if norm:
                    tools.append(norm)
        if tools:
            clean_text = re.sub(r"<[｜\|]{2}DSML[｜\|]{2}[^>]*>.*?(?:</[｜\|]{2}DSML[｜\|]{2}[^>]*>|$)", "", clean_text, flags=re.DOTALL | re.IGNORECASE).strip()
            clean_text = re.sub(r"</?[｜\|]{2}DSML[｜\|]{2}[^>]*>", "", clean_text, flags=re.IGNORECASE).strip()

    if not tools:
        fn_call_pattern = re.compile(r"<function_call>\s*<name>([^<]+)</name>\s*<arguments>(.*?)</arguments>\s*</function_call>", re.DOTALL | re.IGNORECASE)
        for m in fn_call_pattern.finditer(text):
            if fenced(m.start()):
                continue
            name = m.group(1).strip()
            args_raw = m.group(2).strip()
            try:
                args = json.loads(args_raw)
            except Exception:
                args = args_raw
            norm = normalize_tool_call(name, args)
            if norm:
                tools.append(norm)
        if tools:
            clean_text = re.sub(r"<function_call>.*?</function_call>", "", clean_text, flags=re.DOTALL | re.IGNORECASE).strip()

    if not tools:
        tag_regex = re.compile(r"<(?:tool_call|function_call)(?:\s+(?:name|tool|function)=[\x27\x22]([^\x27\x22]+)[\x27\x22])?\s*>", re.IGNORECASE)
        decoder = json.JSONDecoder()
        matches = [m for m in tag_regex.finditer(text) if not fenced(m.start())]
        if matches:
            for m in matches:
                tag_name = m.group(1)
                after_tag = text[m.end():]
                brace_pos = after_tag.find("{")
                if brace_pos != -1:
                    json_substr = after_tag[brace_pos:]
                    data = None
                    try:
                        data, _ = decoder.raw_decode(json_substr)
                    except Exception:
                        pass
                    if not data:
                        cleaned_json = re.sub(r"</?(?:tool_call|function_call|tool_calls|invoke)[^>]*>.*", "", json_substr, flags=re.DOTALL).strip()
                        open_b = cleaned_json.count("{")
                        close_b = cleaned_json.count("}")
                        if open_b > close_b:
                            cleaned_json += "}" * (open_b - close_b)
                        try:
                            data = json.loads(cleaned_json)
                        except Exception:
                            pass
                    if isinstance(data, dict):
                        if tag_name:
                            name = tag_name
                            if "arguments" in data and isinstance(data["arguments"], dict):
                                args = data["arguments"]
                            elif "parameters" in data and isinstance(data["parameters"], dict):
                                args = data["parameters"]
                            elif "input" in data and isinstance(data["input"], dict):
                                args = data["input"]
                            else:
                                args = {k: v for k, v in data.items() if k not in ["name", "tool", "function"]}
                        else:
                            name = data.get("name") or data.get("tool") or data.get("tool_name") or data.get("function") or data.get("action")
                            args = data.get("arguments") or data.get("parameters") or data.get("input") or data.get("args") or data.get("params") or data.get("tool_input") or data.get("action_input")
                            if args is None:
                                args = {}
                        if name:
                            norm = normalize_tool_call(name, args)
                            if norm:
                                tools.append(norm)
            clean_text = re.sub(r"<(?:tool_call|function_call)[^>]*>.*?(?:</(?:tool_call|function_call)>|$)", "", text, flags=re.DOTALL).strip()

    if not tools:
        codeblock_pattern = r"```(?:tool_call|function_call)\s*(.*?)\s*```"
        cb_matches = list(re.finditer(codeblock_pattern, clean_text, flags=re.DOTALL))
        for m in cb_matches:
            cleaned = clean_json_str(m.group(1))
            try:
                data = json.loads(cleaned)
                if isinstance(data, dict):
                    name = data.get("name") or data.get("tool") or data.get("function") or data.get("action")
                    args = data.get("arguments") or data.get("parameters") or data.get("input") or data.get("args") or {}
                    norm = normalize_tool_call(name, args)
                    if norm:
                        tools.append(norm)
            except Exception:
                pass
        if tools:
            clean_text = re.sub(codeblock_pattern, "", clean_text, flags=re.DOTALL).strip()

    if not tools:
        json_pattern = r"```json\s*(\{.*?\})\s*```"
        json_matches = list(re.finditer(json_pattern, clean_text, flags=re.DOTALL))
        for m in json_matches:
            cleaned = clean_json_str(m.group(1))
            try:
                data = json.loads(cleaned)
                if isinstance(data, dict) and ("name" in data or "tool" in data or "function" in data):
                    name = data.get("name") or data.get("tool") or data.get("function") or data.get("action")
                    args = data.get("arguments") or data.get("parameters") or data.get("input") or data.get("args") or {}
                    norm = normalize_tool_call(name, args)
                    if norm:
                        tools.append(norm)
            except Exception:
                pass
        if tools:
            clean_text = re.sub(json_pattern, "", clean_text, flags=re.DOTALL).strip()
    # Keep companion text: the tool-call blocks themselves were already removed
    # from clean_text above; only leftover bare tags are stripped here.
    clean_text = re.sub(r"</?[｜\|]{0,2}(?:DSML[｜\|]{0,2})?\s*(?:tool_calls?|calls|invoke|function_call|parameter)[^>]*>", "", clean_text, flags=re.IGNORECASE).strip()
    return tools, clean_text


# Family-wide closer pattern for the tool-call wrapper family, including
# the |/｜-decorated variants that parse_tools accepts. Used by
# StreamToolParser so a mismatched closer closes the open block instead of
# hanging until flush(). [FIX 3]
_TOOL_END_TAG_RE = re.compile(
    r"</[｜\|]{0,2}(?:DSML[｜\|]{0,2})?\s*(?:tool_calls?|calls|invoke|function_call)\s*>",
    re.IGNORECASE,
)

# [FIX 4] Spaced-DSML dialect: deepseek-harness emits decorated tags with a
# space between the ｜｜DSML｜｜ marker and the tag name, e.g.
# "<｜｜DSML｜｜ invoke name=...>". Entry detection cannot rely on plain
# substring start tags; this regex accepts bars, the DSML marker and the
# space in any combination.
_STREAM_ENTRY_RE = re.compile(
    r"<[｜\|]{0,2}(?:DSML[｜\|]{0,2})?\s*(tool_calls?|calls|function_call|invoke)\b[^>]*>",
    re.IGNORECASE,
)

# Orphan closers trailing a block already closed by the per-tag or family
# fallback (e.g. "</｜｜DSML｜｜ calls>" after the inner invoke was flushed).
_ORPHAN_CLOSER_RE = re.compile(
    r"</[｜\|]{0,2}(?:DSML[｜\|]{0,2})?\s*(?:tool_calls?|calls|function_call|invoke)\s*[｜\|]{0,2}>",
    re.IGNORECASE,
)

# Tag names _STREAM_ENTRY_RE can open on.
_STREAM_ENTRY_TAGS = ("tool_calls", "tool_call", "function_call", "invoke", "calls")

def _skip_bars(text, pos):
    for _ in range(2):
        if pos < len(text) and text[pos] in "|｜":
            pos += 1
    return pos

def _is_plausible_stream_entry_prefix(segment: str) -> bool:
    if not segment.startswith("<") or ">" in segment:
        return False
    body = segment[1:]
    pos = _skip_bars(body, 0)
    length = len(body)
    if pos < length and body[pos] in "Dd":
        matched = 0
        while matched < 4 and pos < length and body[pos].upper() == "DSML"[matched]:
            pos += 1
            matched += 1
        if matched < 4:
            return pos == length
        pos = _skip_bars(body, pos)
    while pos < length and body[pos].isspace():
        pos += 1
    if pos == length:
        return True
    remainder = body[pos:]
    remainder_lower = remainder.lower()
    for tag in _STREAM_ENTRY_TAGS:
        if tag.startswith(remainder_lower):
            return True
        if remainder_lower.startswith(tag):
            suffix = remainder[len(tag):]
            if not suffix or not (suffix[0].isalnum() or suffix[0] == "_"):
                return True
    return False

def _is_plausible_stream_closer_prefix(segment: str) -> bool:
    return segment.startswith("</") and _is_plausible_stream_entry_prefix("<" + segment[2:])


class StreamToolParser:
    def __init__(self):
        self.buffer = ""
        self.in_tool = False
        self.has_tool = False
        self.json_done = False
        self._end_re = None

    def feed(self, chunk):
        self.buffer += chunk
        results = []
        while True:
            if self.in_tool:
                # [FIX 3] Family-wide closer fallback: accept ANY wrapper closer
                # the tool-call family can emit (including |/｜-decorated
                # variants parse_tools tolerates) instead of hanging an open
                # block until flush() when the model closes with a wrong tag.
                # [FIX 4] Prefer the closer for the tag that OPENED the block
                # so nested wrappers (<｜｜DSML｜｜ calls> wrapping invokes)
                # close as one unit; fall back to the family-wide closer for
                # mismatched or decorated closers [FIX 3].
                end_match = self._end_re.search(self.buffer) if self._end_re else None
                if end_match is None:
                    end_match = _TOOL_END_TAG_RE.search(self.buffer)
                if end_match:
                    if not self.json_done:
                        tool_xml = self.buffer[: end_match.end()]
                        parsed, _ = parse_tools(tool_xml)
                        for item in parsed:
                            results.append({"tool": item})
                    self.buffer = self.buffer[end_match.end():]
                    self.in_tool = False
                    self.json_done = False
                    self._end_re = None
                    continue
                brace_idx = self.buffer.find("{")
                if brace_idx != -1 and not self.json_done:
                    decoder = json.JSONDecoder()
                    try:
                        data, consumed = decoder.raw_decode(self.buffer[brace_idx:])
                        norm = normalize_tool_call(data)
                        if norm:
                            results.append({"tool": norm})
                            self.json_done = True
                            self.buffer = self.buffer[brace_idx + consumed:]
                            continue
                    except Exception:
                        pass
                break
            else:
                # [FIX 4] Regex entry detection replaces plain substring finds
                # so decorated/spaced DSML openers enter tool mode.
                m = _STREAM_ENTRY_RE.search(self.buffer)
                if m:
                    start = m.start()
                    if start > 0:
                        results.append({"text": _ORPHAN_CLOSER_RE.sub("", self.buffer[:start])})
                    self.buffer = self.buffer[start:]
                    tag_name = m.group(1).lower()
                    self._end_re = re.compile(
                        r"</[｜\|]{0,2}(?:DSML[｜\|]{0,2})?\s*" + re.escape(tag_name) + r"[｜\|]{0,2}\s*>",
                        re.IGNORECASE,
                    )
                    self.in_tool = True
                    self.has_tool = True
                    continue
                # [FIX 2] Hold an unclosed '<' tail only while it remains a
                # plausible partial match of _STREAM_ENTRY_RE or of a wrapper
                # closer ("</..."), so a split closer is never dumped as prose.
                last_lt = self.buffer.rfind("<")
                tail = self.buffer[last_lt:] if last_lt != -1 else ""
                hold = ">" not in tail and (
                    _is_plausible_stream_entry_prefix(tail)
                    or _is_plausible_stream_closer_prefix(tail)
                )
                if last_lt != -1 and hold:
                    if last_lt > 0:
                        results.append({"text": _ORPHAN_CLOSER_RE.sub("", self.buffer[:last_lt])})
                    self.buffer = tail
                    break
                if self.buffer:
                    results.append({"text": _ORPHAN_CLOSER_RE.sub("", self.buffer)})
                self.buffer = ""
                break
        return results

    def flush(self):
        out = []
        if self.buffer and not self.in_tool:
            out.append({"text": self.buffer})
        elif self.in_tool:
            # [FIX 1] Recover the tool before stripping: if the stream was cut
            # off before the closing tag arrived but the payload itself is
            # parseable, emit the tool call instead of dumping raw parameter
            # values into the chat text. Strip only when nothing parses.
            parsed, _ = parse_tools(self.buffer)
            if parsed:
                for item in parsed:
                    out.append({"tool": item})
            elif not self.json_done:
                stripped = re.sub(
                    r"</?[｜\|]{0,2}(?:DSML[｜\|]{0,2})?\s*(?:tool_calls?|calls|invoke|function_call|parameter)[^>]*>",
                    "",
                    self.buffer,
                    flags=re.IGNORECASE,
                ).strip()
                if stripped:
                    out.append({"text": stripped})
            # With json_done set, whatever is left after the consumed JSON
            # payload is wrapper noise (partial closers / whitespace) and is
            # dropped instead of leaking into the chat text.
        self.buffer = ""
        self.in_tool = False
        self.json_done = False
        self._end_re = None
        return out

