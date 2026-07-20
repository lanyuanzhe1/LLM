import re
import unicodedata
from collections import defaultdict

from app.schemas.tools import (
    CitationCoverage,
    CitationValidateRequest,
    CitationValidateResponse,
)
from app.rag.evidence import canonical_display_label


REQUIRED_SECTIONS = ("结论", "依据", "适用条件", "不确定性", "来源")
SUBSTANTIVE_SECTIONS = REQUIRED_SECTIONS[:-1]
SUBSTANTIVE_PLAIN_TEXT_INSTRUCTION = (
    "“结论”“依据”“适用条件”“不确定性”章节只能使用纯文本、正常标点和"
    "合法 `[E#]` 行内引用；不得输出 HTML、HTML 实体、Markdown 格式、"
    "链接、图片或反斜杠转义，不得使用 Markdown block、引用后链接或定义、"
    "裸 URL、任意 scheme:// 链接或危险 scheme。"
)
SOURCE_BIBLIOGRAPHY_INSTRUCTION = (
    "“来源”章节每个非空行必须完整写为 `[E#] description`；允许不加列表标记，"
    "或仅在行首使用 `- `、`* `、`+ `、`1. ` 形式的正整数有序标记；"
    "`description` 必须精确等于证据的 title、source 或 `title — source`，"
    "不得追加其他文本。"
)
SECTION_HEADING_PATTERN = re.compile(
    r"^\s*(?:#{1,6}\s*)?"
    r"(结论|依据|适用条件|不确定性|来源)"
    r"\s*[:：]?\s*$"
)
UNKNOWN_HEADING_PATTERN = re.compile(r"^\s*#{1,6}\s*\S")
SOURCE_LIST_MARKER_PATTERN = r"(?:(?:[\-\*\+]|[1-9]\d*\.)[ \t]+)?"
SOURCE_ENTRY_PATTERN = re.compile(
    rf"^{SOURCE_LIST_MARKER_PATTERN}"
    r"\[(?P<alias>E\d+)\][ \t]+(?P<description>\S(?:.*\S)?)$"
)
INLINE_CITATION_TOKEN_PATTERN = re.compile(r"\[E\d+\]")
MARKDOWN_BLOCK_PATTERN = re.compile(
    r"^(?:"
    r" {4}"
    r"| {0,3}(?:[-*+>][ ]|#{1,6}(?:[ ]|$)|[0-9]+[.)][ ])"
    r"| {0,3}(?:-{3,}|={3,})[ ]*$"
    r")"
)
BARE_URL_PATTERN = re.compile(
    r"(?:"
    r"[a-z][a-z0-9+.-]*://"
    r"|(?:https?|ftp|file):/"
    r"|(?:javascript|data|vbscript|mailto|tel):"
    r"|www\."
    r")",
    re.IGNORECASE,
)
CRITICAL_PATTERN = re.compile(
    r"\d+"
    r"|℃|°c|%|ppm|mg|kg"
    r"|法律|法规|标准|条款|必须|禁止|应当"
    r"|药剂|磷化铝|熏蒸|制冷|设备控制"
)
HAN_CRITICAL_PATTERN = re.compile(
    r"法律|法规|标准|条款|必须|禁止|应当"
    r"|药剂|磷化铝|熏蒸|制冷|设备控制"
    r"|(?:立即|执行|进行|开展)"
    r"(?:仓房|粮仓|仓库|仓内|粮堆|储粮|粮食|谷物)?通风"
    r"|通风(?:处理|作业|操作|控制)"
    r"|(?:建议|推荐)(?:对)?"
    r"(?:仓房|粮仓|仓库|仓内|粮堆|储粮|粮食|谷物)?"
    r"(?:进行|采用|使用|开始|执行|开展)?通风"
    r"|可以?(?:通过|采用|使用|进行|开始|执行|开展)"
    r"(?:仓房|粮仓|仓库|仓内|粮堆|储粮|粮食|谷物)?通风"
)
CHINESE_NUMBER = r"[零〇一二两三四五六七八九十百千万亿两]+"
CHINESE_MEASUREMENT_PATTERN = re.compile(
    rf"(?:百分之{CHINESE_NUMBER}|{CHINESE_NUMBER}"
    r"(?:摄氏度|毫克|千克|公斤|克|度))"
)
ENGLISH_CRITICAL_PATTERN = re.compile(
    r"\baluminum\s+phosphide\b"
    r"|\bfumigat(?:e|es|ed|ing|ion)\b"
    r"|\bventilat(?:e|es|ed|ing)\b"
    r"|\b(?:begin|start|perform|recommend|use)\s+ventilation\b"
    r"|\bventilation\b"
    r"(?:\s+of\s+(?:the\s+)?"
    r"(?:grain|granary|warehouse|storage\s+facility))?"
    r"\s+(?:is\s+)?recommended\b"
    r"|\bventilation\b.{0,20}\bimmediately\b",
    re.IGNORECASE,
)
VALID_CITATION_PATTERN = re.compile(r"\[(E\d+)\]")
CITATION_CANDIDATE_PATTERN = re.compile(
    r"(?P<open>[\[［])(?P<token>[^\]］\r\n]*)(?P<close>[\]］])"
)
INVALID_ALIAS_PATTERN = re.compile(
    r"(?:E[A-Za-z0-9_-]*|[A-Z]\d+[A-Za-z0-9_-]*)$"
)
UNMATCHED_LEFT_PATTERN = re.compile(
    r"[\[［](?P<token>[^\]］\r\n]*)(?=$|\r?$)", re.MULTILINE
)
SENTENCE_PATTERN = re.compile(
    r"(?:[^。！？.!?;；]|\.(?=\d))+"
    r"(?:(?:[。！？!?;；]+|\.(?!\d))(?:[ \t]*\[[^\]\r\n]+\])*)?"
)
SUBSTANTIVE_TEXT_PATTERN = re.compile(r"[\w\u3400-\u9fff]")
MAX_PUBLIC_ITEMS = 20
CITATION_DIGITS = frozenset("0123456789０１２３４５６７８９")
MARKDOWN_FORMAT_SEPARATORS = frozenset("*_~`")
TECHNICAL_SYMBOLS = frozenset("±×‰·⁺⁻−+=≤≥/%％°℃")
# These exact punctuation characters stay visible after canonicalization and
# therefore preserve a real word boundary. Decimal compatibility forms are
# separately safe because every Unicode Number is treated as critical.
SAFE_VISIBLE_COMPATIBILITY_BOUNDARIES = frozenset(
    "。，、；：！？.,;:!?（）()“”‘’\"'《》〈〉—–-…/"
)
PLAIN_TEXT_PUNCTUATION = frozenset(
    "。，、；：！？"
    ".,;:!?"
    "（）()"
    "“”‘’\"'"
    "《》〈〉"
    "—–-…·"
    "/%％‰°℃"
    "+=≤≥"
    "±×⁺⁻−"
)


def _parse_sections(
    answer: str,
) -> tuple[
    dict[str, list[list[str]]],
    list[tuple[str, list[str]]],
    list[str],
]:
    occurrences: dict[str, list[list[str]]] = defaultdict(list)
    ordered: list[tuple[str, list[str]]] = []
    outside: list[str] = []
    current_body: list[str] | None = None
    for line in re.split(r"\r\n|[\r\n]", answer):
        normalized_line = unicodedata.normalize("NFKC", line)
        match = SECTION_HEADING_PATTERN.fullmatch(normalized_line)
        if match:
            section = match.group(1)
            current_body = []
            occurrences[section].append(current_body)
            ordered.append((section, current_body))
        elif current_body is None or UNKNOWN_HEADING_PATTERN.match(
            normalized_line
        ):
            outside.append(line)
        else:
            current_body.append(line)
    return dict(occurrences), ordered, outside


def _sentences(lines: list[str]) -> list[str]:
    return [
        match.group(0).strip()
        for match in SENTENCE_PATTERN.finditer("\n".join(lines))
        if match.group(0).strip()
    ]


def _is_substantive(sentence: str) -> bool:
    without_citations = VALID_CITATION_PATTERN.sub("", sentence)
    return bool(SUBSTANTIVE_TEXT_PATTERN.search(without_citations))


def _ordered_unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


def _is_spacing_or_format(char: str) -> bool:
    return char.isspace() or unicodedata.category(char) == "Cf"


def _is_citation_lookalike(token: str) -> bool:
    compact = "".join(
        char
        for char in token
        if not _is_spacing_or_format(char)
    )
    normalized = unicodedata.normalize("NFKC", compact)
    if INVALID_ALIAS_PATTERN.fullmatch(normalized) or normalized.startswith("E"):
        return True
    return bool(
        normalized.startswith("e")
        and len(normalized) > 1
        and normalized[1] in "0123456789_-"
    )


def _has_citation_start_boundary(text: str, index: int) -> bool:
    return index == 0 or not (
        text[index - 1].isalnum() or text[index - 1] in "_-"
    )


def _has_unmatched_right_lookalike(
    text: str,
    candidates: list[re.Match[str]],
) -> bool:
    candidate_index = 0
    for right_index, char in enumerate(text):
        if char not in "]］":
            continue
        while (
            candidate_index < len(candidates)
            and candidates[candidate_index].end() <= right_index
        ):
            candidate_index += 1
        if (
            candidate_index < len(candidates)
            and candidates[candidate_index].start()
            <= right_index
            < candidates[candidate_index].end()
        ):
            continue

        cursor = right_index - 1
        while cursor >= 0 and _is_spacing_or_format(text[cursor]):
            cursor -= 1
        saw_digit = False
        while cursor >= 0:
            if text[cursor] in CITATION_DIGITS:
                saw_digit = True
                cursor -= 1
            elif _is_spacing_or_format(text[cursor]):
                cursor -= 1
            else:
                break
        if (
            saw_digit
            and cursor >= 0
            and text[cursor] in "EeＥｅ"
            and _has_citation_start_boundary(text, cursor)
        ):
            if _is_citation_lookalike(text[cursor:right_index]):
                return True
    return False


def _citation_findings(
    text: str,
    aliases: dict[str, str],
) -> tuple[list[str], list[str], bool]:
    valid: list[str] = []
    invalid: list[str] = []
    candidates = list(CITATION_CANDIDATE_PATTERN.finditer(text))
    malformed = any(
        _is_citation_lookalike(match.group("token"))
        for match in UNMATCHED_LEFT_PATTERN.finditer(text)
    ) or _has_unmatched_right_lookalike(text, candidates)
    for match in candidates:
        token = match.group("token")
        raw_ascii_brackets = (
            match.group("open") == "[" and match.group("close") == "]"
        )
        if raw_ascii_brackets and re.fullmatch(r"E\d+", token):
            if token in aliases:
                valid.append(token)
            else:
                invalid.append(token)
        elif raw_ascii_brackets and INVALID_ALIAS_PATTERN.fullmatch(token):
            invalid.append(token)
        elif _is_citation_lookalike(token):
            malformed = True
    return valid, sorted(set(invalid)), malformed


def _has_substantive_content(body: list[str]) -> bool:
    return any(_is_substantive(sentence) for sentence in _sentences(body))


def _is_han(character: str) -> bool:
    # Includes unified extensions and the two CJK compatibility-ideograph
    # blocks, whose raw script identity is already Han.
    codepoint = ord(character)
    return (
        0x3400 <= codepoint <= 0x4DBF
        or 0x4E00 <= codepoint <= 0x9FFF
        or 0xF900 <= codepoint <= 0xFAFF
        or 0x20000 <= codepoint <= 0x323AF
    )


def _technical_separators_form_critical(line: str) -> bool:
    technical_prefix = [0]
    for character in line:
        technical_prefix.append(
            technical_prefix[-1] + (character in TECHNICAL_SYMBOLS)
        )

    run_han: list[str] = []
    run_positions: list[int] = []

    def run_is_unsafe() -> bool:
        collapsed = "".join(run_han)
        for match in HAN_CRITICAL_PATTERN.finditer(collapsed):
            start = run_positions[match.start()]
            end = run_positions[match.end() - 1]
            if technical_prefix[end] > technical_prefix[start + 1]:
                return True
        return False

    for index, character in enumerate(line):
        if _is_han(character):
            run_han.append(character)
            run_positions.append(index)
        elif character in TECHNICAL_SYMBOLS or character.isspace():
            continue
        else:
            if run_is_unsafe():
                return True
            run_han.clear()
            run_positions.clear()
    return run_is_unsafe()


def _has_unsafe_script_or_symbol_context(line: str) -> bool:
    next_non_space: list[str | None] = [None] * len(line)
    following: str | None = None
    for index in range(len(line) - 1, -1, -1):
        next_non_space[index] = following
        if not line[index].isspace():
            following = line[index]

    previous: str | None = None
    for index, character in enumerate(line):
        normalized = unicodedata.normalize("NFKC", character)
        if (
            not _is_han(character)
            and any(_is_han(item) for item in normalized)
        ):
            return True
        between_han = (
            previous is not None
            and next_non_space[index] is not None
            and _is_han(previous)
            and _is_han(next_non_space[index])
        )
        if (
            normalized != character
            and not _is_han(character)
            and between_han
            and not (
                normalized
                and (
                    all(
                        item in SAFE_VISIBLE_COMPATIBILITY_BOUNDARIES
                        for item in normalized
                    )
                    or all(item.isdecimal() for item in normalized)
                )
            )
        ):
            return True
        if not character.isspace():
            previous = character
    return _technical_separators_form_critical(line)


def _citation_opens_link_or_definition(line: str, end: int) -> bool:
    cursor = end
    while cursor < len(line) and line[cursor].isspace():
        cursor += 1
    return cursor < len(line) and line[cursor] in "(:"


def _line_has_closed_substantive_format(line: str) -> bool:
    if (
        MARKDOWN_BLOCK_PATTERN.match(line)
        or BARE_URL_PATTERN.search(line)
        or _has_unsafe_script_or_symbol_context(line)
    ):
        return False
    cursor = 0
    while cursor < len(line):
        character = line[cursor]
        if character == "[":
            citation = INLINE_CITATION_TOKEN_PATTERN.match(line, cursor)
            if citation is None:
                return False
            if _citation_opens_link_or_definition(line, citation.end()):
                return False
            cursor = citation.end()
            continue
        category = unicodedata.category(character)
        if (
            category[0] in {"L", "N"}
            or category == "Zs"
            or character in PLAIN_TEXT_PUNCTUATION
        ):
            cursor += 1
            continue
        return False
    return True


def _has_closed_substantive_format(body: list[str]) -> bool:
    return all(
        _line_has_closed_substantive_format(line)
        and _line_has_closed_substantive_format(
            unicodedata.normalize("NFKC", line)
        )
        for line in body
    )


def _strip_critical_ignored(text: str) -> str:
    return "".join(
        character
        for character in text
        if not character.isspace()
        and unicodedata.category(character)[0] not in {"C", "M"}
        and character not in MARKDOWN_FORMAT_SEPARATORS
    )


def _critical_security_canonical(sentence: str) -> str:
    normalized = unicodedata.normalize("NFKC", sentence)
    before_casefold = _strip_critical_ignored(normalized)
    return _strip_critical_ignored(before_casefold.casefold())


def _critical_boundary_canonical(sentence: str) -> str:
    normalized = unicodedata.normalize("NFKC", sentence).casefold()
    cleaned = "".join(
        " " if character.isspace() else character
        for character in normalized
        if unicodedata.category(character)[0] not in {"C", "M"}
        and character not in MARKDOWN_FORMAT_SEPARATORS
    )
    return " ".join(cleaned.split())


def _is_critical(sentence: str) -> bool:
    canonical = _critical_security_canonical(sentence)
    boundary_canonical = _critical_boundary_canonical(sentence)
    without_citations = VALID_CITATION_PATTERN.sub("", sentence)
    return bool(
        CRITICAL_PATTERN.search(canonical)
        or HAN_CRITICAL_PATTERN.search(canonical)
        or CHINESE_MEASUREMENT_PATTERN.search(canonical)
        or ENGLISH_CRITICAL_PATTERN.search(boundary_canonical)
        or any(
            unicodedata.category(character)[0] == "N"
            for character in without_citations
        )
    )


def _line_has_renderer_safe_source_format(line: str) -> bool:
    if MARKDOWN_BLOCK_PATTERN.match(line) or BARE_URL_PATTERN.search(line):
        return False
    return all(
        unicodedata.category(character)[0] in {"L", "N"}
        or unicodedata.category(character) == "Zs"
        or character in PLAIN_TEXT_PUNCTUATION
        for character in line
    )


def _has_renderer_safe_source_format(description: str) -> bool:
    return _line_has_renderer_safe_source_format(
        description
    ) and _line_has_renderer_safe_source_format(
        unicodedata.normalize("NFKC", description)
    )


def _source_declarations(
    body: list[str],
    aliases: dict[str, str],
    evidence_descriptions: dict[str, frozenset[str]],
) -> tuple[list[str], bool]:
    declared: list[str] = []
    invalid = False
    for line in body:
        if not line.strip():
            continue
        if any(
            unicodedata.category(character) in {"Cc", "Cf"}
            for character in line
        ):
            invalid = True
            continue
        match = SOURCE_ENTRY_PATTERN.fullmatch(line.strip())
        if match is None:
            invalid = True
            continue
        alias = match.group("alias")
        description = match.group("description")
        if (
            alias not in aliases
            or not _has_renderer_safe_source_format(description)
            or description not in evidence_descriptions.get(alias, frozenset())
        ):
            invalid = True
            continue
        declared.append(alias)
    return declared, invalid


def _bounded(items: list[str], truncation_error: str, errors: list[str]) -> list[str]:
    if len(items) <= MAX_PUBLIC_ITEMS:
        return items
    errors.append(truncation_error)
    return items[:MAX_PUBLIC_ITEMS]


def _bounded_errors(errors: list[str]) -> list[str]:
    if len(errors) <= MAX_PUBLIC_ITEMS:
        return errors
    return [*errors[: MAX_PUBLIC_ITEMS - 1], "错误列表已截断"]


class CitationValidator:
    def validate(self, request: CitationValidateRequest) -> CitationValidateResponse:
        aliases = {
            f"E{index}": item.evidence_id
            for index, item in enumerate(request.evidences, start=1)
        }
        evidence_descriptions = {
            f"E{index}": frozenset(
                {
                    canonical_display_label(item.title),
                    canonical_display_label(item.source),
                    f"{canonical_display_label(item.title)} — "
                    f"{canonical_display_label(item.source)}",
                }
            )
            for index, item in enumerate(request.evidences, start=1)
        }
        sections, ordered_sections, outside_lines = _parse_sections(
            request.answer
        )
        errors: list[str] = []
        if any(
            section in SUBSTANTIVE_SECTIONS
            and not _has_closed_substantive_format(body)
            for section, body in ordered_sections
        ):
            errors.append("正文包含不允许的格式")
        if _has_substantive_content(outside_lines):
            errors.append("章节之外包含实质内容")
        if [section for section, _ in ordered_sections] != list(
            REQUIRED_SECTIONS
        ):
            errors.append("章节顺序无效")
        for section in REQUIRED_SECTIONS:
            bodies = sections.get(section, [])
            if not bodies:
                errors.append(f"缺少必要章节：{section}")
                continue
            if len(bodies) > 1:
                errors.append(f"重复章节：{section}")
            if any(not _has_substantive_content(body) for body in bodies):
                errors.append(f"章节内容为空：{section}")

        _, invalid_aliases, malformed_citations = _citation_findings(
            request.answer, aliases
        )
        if invalid_aliases:
            errors.append(f"包含无效引用：{', '.join(invalid_aliases)}")
        if malformed_citations:
            errors.append("包含格式错误的引用")

        substantive_sentences: list[str] = []
        source_aliases: list[str] = []
        used_aliases: list[str] = []
        unsupported: list[str] = []
        cited_sentences = 0
        for section, body in ordered_sections:
            if section == "来源":
                declarations, invalid_declaration = _source_declarations(
                    body,
                    aliases,
                    evidence_descriptions,
                )
                source_aliases.extend(declarations)
                if invalid_declaration:
                    errors.append("来源条目格式无效")
                continue
            if section not in SUBSTANTIVE_SECTIONS:
                continue
            for sentence in _sentences(body):
                if not _is_substantive(sentence):
                    continue
                substantive_sentences.append(sentence)
                valid_inline_aliases = _citation_findings(sentence, aliases)[0]
                if valid_inline_aliases:
                    cited_sentences += 1
                    used_aliases.extend(valid_inline_aliases)
                if _is_critical(sentence) and not valid_inline_aliases:
                    unsupported.append(sentence)

        used_aliases = _ordered_unique(used_aliases)
        duplicated_source_aliases = sorted(
            {
                alias
                for alias in source_aliases
                if source_aliases.count(alias) > 1
            }
        )
        if duplicated_source_aliases:
            errors.append(
                "来源包含重复引用：" + ", ".join(duplicated_source_aliases)
            )
        source_aliases = _ordered_unique(source_aliases)
        missing_source_aliases = [
            alias for alias in used_aliases if alias not in source_aliases
        ]
        unused_source_aliases = [
            alias for alias in source_aliases if alias not in used_aliases
        ]
        if missing_source_aliases:
            errors.append(
                "正文引用未在来源中声明："
                + ", ".join(missing_source_aliases)
            )
        if unused_source_aliases:
            errors.append(
                "来源包含未使用引用：" + ", ".join(unused_source_aliases)
            )
        if unsupported:
            errors.append("关键结论缺少引用")
        citation_ids = _ordered_unique([aliases[alias] for alias in used_aliases])
        if not citation_ids:
            errors.append("回答没有使用任何检索证据")
        total_sentences = len(substantive_sentences)
        ratio = cited_sentences / total_sentences if total_sentences else 0.0
        unsupported = _bounded(
            unsupported,
            "不支持句子列表已截断",
            errors,
        )
        errors = _bounded_errors(errors)
        return CitationValidateResponse(
            request_id=request.request_id,
            valid=not errors,
            errors=errors,
            unsupported_sentences=unsupported,
            citation_ids=citation_ids,
            coverage=CitationCoverage(
                total_sentences=total_sentences,
                cited_sentences=cited_sentences,
                ratio=ratio,
            ),
        )
