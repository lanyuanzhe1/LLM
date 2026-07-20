import multiprocessing
import unicodedata

import pytest
from pydantic import ValidationError

from app.rag.evidence import Evidence
from app.schemas.tools import CitationValidateRequest
from app.services.citation_validation import (
    PLAIN_TEXT_PUNCTUATION,
    TECHNICAL_SYMBOLS,
    CitationValidator,
    _has_closed_substantive_format,
    _is_critical,
)


EVIDENCE = Evidence(
    evidence_id="sha256:e1",
    document_id="sha256:d1",
    title="低温储粮",
    source="paper.pdf",
    text="低温能够抑制害虫活动。",
    score=0.9,
    authority_level="unknown",
)
EVIDENCE_2 = Evidence(
    evidence_id="sha256:e2",
    document_id="sha256:d2",
    title="粮情监测",
    source="monitoring.pdf",
    text="监测结果需要结合仓储条件解释。",
    score=0.8,
    authority_level="unknown",
)


def _validate(answer: str, evidences=None):
    return CitationValidator().validate(
        CitationValidateRequest(
            request_id="req",
            answer=answer,
            evidences=evidences or [EVIDENCE],
        )
    )


def _complete_answer(conclusion: str, *, source: str = "[E1] 低温储粮") -> str:
    return f"""## 结论
{conclusion}
## 依据
证据表明低温具有抑制作用。[E1]
## 适用条件
需结合粮种与仓储条件。
## 不确定性
知识库没有统一阈值。
## 来源
{source}"""


def _check_long_compatibility_space_line(queue) -> None:
    line = "A" + "\u2002" * 32_768 + "B。[E1]"
    queue.put(_has_closed_substantive_format([line]))


def test_ascii_sentence_terminators_do_not_share_citations_with_later_claims():
    response = _validate(
        _complete_answer("该措施有依据.[E1] 后续必须保持10℃;")
    )

    assert response.valid is False
    assert "后续必须保持10℃;" in response.unsupported_sentences
    assert response.coverage.cited_sentences == 2


def test_decimal_points_stay_with_cited_and_uncited_measurement_sentences():
    response = _validate(
        _complete_answer("粮温13.5℃。[E1] 另一测点14.2℃。第三测点15.0℃。")
    )

    assert response.valid is False
    assert response.unsupported_sentences == [
        "另一测点14.2℃。",
        "第三测点15.0℃。",
    ]
    assert response.coverage.total_sentences == 6
    assert response.coverage.cited_sentences == 2


def test_critical_units_are_unicode_and_case_normalized():
    response = _validate(
        _complete_answer("浓度单位为ＰＰＭ。温度单位为°Ｃ。")
    )

    assert response.valid is False
    assert response.unsupported_sentences == [
        "浓度单位为ＰＰＭ。",
        "温度单位为°Ｃ。",
    ]


def test_heading_normalizes_unicode_whitespace_but_rejects_trailing_markup():
    valid = _validate(
        """＃＃　结论：
低温能够抑制害虫活动。[E1]
＃＃　依据：
证据表明低温具有抑制作用。[E1]
＃＃　适用条件：
需结合粮种与仓储条件。
＃＃　不确定性：
知识库没有统一阈值。
＃＃　来源：
[E1] 低温储粮"""
    )
    malformed = _validate(
        _complete_answer("低温能够抑制害虫活动。[E1]").replace(
            "## 结论", "结论 ###"
        )
    )

    assert valid.valid is True
    assert malformed.valid is False
    assert "缺少必要章节：结论" in malformed.errors


def test_punctuation_only_section_body_is_empty():
    response = _validate(_complete_answer("。。。"))

    assert response.valid is False
    assert "章节内容为空：结论" in response.errors


def test_citation_looking_malformed_forms_are_rejected_without_normalizing_them():
    response = _validate(
        _complete_answer(
            "低温能够抑制害虫活动。[E1][e1][E1,E2][E1 E1]［Ｅ１］[E1 E1"
        )
    )

    assert response.valid is False
    assert "包含格式错误的引用" in response.errors


@pytest.mark.parametrize("lookalike", ["[ E1 ]", "[E1 ]", "[ E1]"])
def test_whitespace_decorated_citation_aliases_are_malformed(lookalike):
    response = _validate(
        _complete_answer(f"低温能够抑制害虫活动。[E1]{lookalike}")
    )

    assert response.valid is False
    assert "包含格式错误的引用" in response.errors


@pytest.mark.parametrize(
    "lookalike",
    [
        "［　Ｅ１　］",
        "[\u200bE1\u200b]",
        "[\u200cE1\u200c]",
        "[\u200dE1\u200d]",
        "[\ufeffE1\ufeff]",
        "[\u202fE1\u202f]",
        "［\u200bＥ１\u200b］",
    ],
)
def test_unicode_decorated_citation_aliases_are_malformed(lookalike):
    response = _validate(
        _complete_answer(f"低温能够抑制害虫活动。[E1]{lookalike}")
    )

    assert response.valid is False
    assert "包含格式错误的引用" in response.errors


@pytest.mark.parametrize(
    "bracket_text",
    [
        "[note]",
        "[value]",
        "[source]",
        "[example]",
        "[email]",
        "[etc.]",
        "[注意]",
        "［说明］",
    ],
)
def test_non_citation_bracket_constructs_are_rejected(bracket_text):
    response = _validate(
        _complete_answer(f"低温能够抑制害虫活动。{bracket_text}[E1]")
    )

    assert response.valid is False
    assert "正文包含不允许的格式" in response.errors


def test_ordinary_prose_cannot_end_with_unauthorized_bracket_text():
    response = _validate(
        _complete_answer("低温能够抑制害虫活动。[E1] 补充说明[note]")
    )

    assert response.valid is False
    assert "正文包含不允许的格式" in response.errors


@pytest.mark.parametrize(
    "remnant",
    [
        "E\u200b1]",
        "e\u200c1]",
        "Ｅ\ufeff１］",
        "E 1]",
        "Ｅ\u3000１］",
        "E\u20601]",
        "E" + "\u200b" * 33 + "1]",
        "E1 ]",
        "E1\u2060]",
        "E1\u200b2]",
        "E\u200b1\u200b]",
        "Ｅ１　］",
        "Ｅ１\u2060］",
        "Ｅ１\u200b２］",
        "Ｅ\u200b１\u200b］",
    ],
)
def test_decorated_unmatched_right_aliases_are_rejected_in_body_and_source(remnant):
    body_response = _validate(
        _complete_answer(f"低温能够抑制害虫活动。[E1] {remnant}")
    )
    source_response = _validate(
        _complete_answer(
            "低温能够抑制害虫活动。[E1]",
            source=f"[E1] 低温储粮 {remnant}",
        )
    )

    for response in (body_response, source_response):
        assert response.valid is False
        assert "包含格式错误的引用" in response.errors


def test_excess_unsupported_sentences_are_capped_without_raising():
    response = _validate(
        _complete_answer("".join(f"必须执行{i};" for i in range(25)))
    )

    assert response.valid is False
    assert len(response.unsupported_sentences) == 20
    assert "不支持句子列表已截断" in response.errors
    assert response.coverage.total_sentences == 28


def test_duplicate_input_evidence_ids_are_rejected_before_validation():
    duplicate = EVIDENCE.model_copy(update={"title": "重复证据"})

    with pytest.raises(ValidationError):
        CitationValidateRequest(
            request_id="req",
            answer=_complete_answer(
                "先使用第一条证据。[E1] 再使用重复证据。[E2]",
                source="[E1] 低温储粮\n[E2] 重复证据",
            ),
            evidences=[EVIDENCE, duplicate],
        )


def test_valid_answer_requires_sections_and_allowed_alias():
    answer = """## 结论
低温能够抑制害虫活动。[E1]
## 依据
证据表明低温具有抑制作用。[E1]
## 适用条件
需结合粮种与仓储条件。
## 不确定性
知识库未提供统一温度阈值。
## 来源
[E1] 低温储粮"""
    response = _validate(answer)
    assert response.valid is True
    assert response.citation_ids == ["sha256:e1"]
    assert response.coverage.total_sentences == 4
    assert response.coverage.cited_sentences == 2
    assert response.coverage.ratio == 0.5


@pytest.mark.parametrize(
    "preamble",
    [
        "立即执行设备控制并开始熏蒸。",
        "以下是根据知识库整理的回答。",
    ],
)
def test_substantive_preamble_before_first_heading_is_rejected(preamble):
    response = _validate(
        f"{preamble}\n"
        + _complete_answer("低温能够抑制害虫活动。[E1]")
    )

    assert response.valid is False
    assert "章节之外包含实质内容" in response.errors


def test_required_sections_must_follow_the_declared_order():
    answer = """## 依据
证据表明低温具有抑制作用。[E1]
## 结论
低温能够抑制害虫活动。[E1]
## 适用条件
需结合粮种与仓储条件。
## 不确定性
知识库没有统一阈值。
## 来源
[E1] 低温储粮"""

    response = _validate(answer)

    assert response.valid is False
    assert "章节顺序无效" in response.errors


@pytest.mark.parametrize(
    "source_suffix",
    [
        "立即执行设备控制并开始熏蒸。",
        "这是来源之后的补充说明。",
        "[E1]\u200b 隐藏装饰文本",
    ],
)
def test_every_nonempty_source_line_must_be_a_citation_declaration(
    source_suffix,
):
    response = _validate(
        _complete_answer(
            "低温能够抑制害虫活动。[E1]",
            source=f"[E1] 低温储粮\n{source_suffix}",
        )
    )

    assert response.valid is False
    assert "来源条目格式无效" in response.errors


def test_valid_multiline_bibliography_remains_accepted():
    response = _validate(
        """## 结论
低温证据与监测证据需要结合使用。[E1][E2]
## 依据
两项证据分别提供储粮与监测信息。[E1][E2]
## 适用条件
需结合粮种与仓储条件。
## 不确定性
知识库没有统一阈值。
## 来源
[E1] 低温储粮
[E2] 粮情监测""",
        [EVIDENCE, EVIDENCE_2],
    )

    assert response.valid is True
    assert response.citation_ids == [
        EVIDENCE.evidence_id,
        EVIDENCE_2.evidence_id,
    ]


@pytest.mark.parametrize(
    "marker",
    ["", "- ", "* ", "+ ", "1. ", "27. "],
)
def test_source_bibliography_accepts_controlled_optional_list_markers(marker):
    response = _validate(
        _complete_answer(
            "低温能够抑制害虫活动。[E1]",
            source=f"{marker}[E1] 低温储粮",
        )
    )

    assert response.valid is True
    assert response.citation_ids == [EVIDENCE.evidence_id]


@pytest.mark.parametrize(
    "source",
    [
        "- [E1] 低温储粮 **已验证**",
        "1. [E1] 低温储粮 额外说明",
        "* [E1]\u200b 低温储粮",
        "+ [E1] 低温储粮 立即执行磷化铝熏蒸",
        "- [E1] **低温储粮**",
    ],
)
def test_source_list_markers_do_not_allow_decorated_or_hidden_tail(source):
    response = _validate(
        _complete_answer(
            "低温能够抑制害虫活动。[E1]",
            source=source,
        )
    )

    assert response.valid is False
    assert "来源条目格式无效" in response.errors


def test_plain_and_markdown_headings_accept_ascii_and_chinese_colons():
    answer = """结论：
低温能够抑制害虫活动。[E1]
## 依据:
证据表明低温具有抑制作用。[E1]
适用条件
需结合粮种与仓储条件。
### 不确定性：
知识库没有统一阈值。
来源:
[E1] 低温储粮"""

    response = _validate(answer)

    assert response.valid is True
    assert response.citation_ids == [EVIDENCE.evidence_id]


def test_section_heading_must_be_standalone():
    response = _validate(
        "结论：低温储粮；依据：经验；适用条件：一般；"
        "不确定性：未知；来源：[E1]。"
    )

    assert response.valid is False
    assert "缺少必要章节：结论" in response.errors


def test_empty_required_section_is_rejected():
    answer = """## 结论
## 依据
证据表明低温具有抑制作用。[E1]
## 适用条件
需结合粮种与仓储条件。
## 不确定性
知识库没有统一阈值。
## 来源
[E1] 低温储粮"""

    response = _validate(answer)

    assert response.valid is False
    assert "章节内容为空：结论" in response.errors


def test_duplicate_required_section_is_rejected():
    answer = """## 结论
低温能够抑制害虫活动。[E1]
## 依据
证据表明低温具有抑制作用。[E1]
## 结论:
重复结论。[E1]
## 适用条件
需结合粮种与仓储条件。
## 不确定性
知识库没有统一阈值。
## 来源
[E1] 低温储粮"""

    response = _validate(answer)

    assert response.valid is False
    assert "重复章节：结论" in response.errors


def test_source_only_alias_is_not_counted_as_a_used_citation():
    answer = """## 结论
低温能够抑制害虫活动。
## 依据
证据表明低温具有抑制作用。
## 适用条件
需结合粮种与仓储条件。
## 不确定性
知识库没有统一阈值。
## 来源
[E1] 低温储粮"""

    response = _validate(answer)

    assert response.valid is False
    assert response.citation_ids == []
    assert "来源包含未使用引用：E1" in response.errors
    assert "回答没有使用任何检索证据" in response.errors


def test_inline_alias_must_be_declared_in_sources():
    answer = """## 结论
低温能够抑制害虫活动。[E1]
## 依据
证据表明低温具有抑制作用。[E1]
## 适用条件
需结合粮种与仓储条件。
## 不确定性
知识库没有统一阈值。
## 来源
低温储粮"""

    response = _validate(answer)

    assert response.valid is False
    assert "正文引用未在来源中声明：E1" in response.errors


def test_source_section_must_not_declare_unused_aliases():
    answer = """## 结论
低温能够抑制害虫活动。[E1]
## 依据
证据表明低温具有抑制作用。[E1]
## 适用条件
需结合粮种与仓储条件。
## 不确定性
知识库没有统一阈值。
## 来源
[E1] 低温储粮
[E2] 粮情监测"""

    response = _validate(answer, [EVIDENCE, EVIDENCE_2])

    assert response.valid is False
    assert "来源包含未使用引用：E2" in response.errors


def test_citation_ids_follow_first_substantive_use_not_source_order():
    answer = """## 结论
先结合监测证据。[E2] 再参考低温证据。[E1]
## 依据
两项证据共同支持说明。[E2][E1]
## 适用条件
需结合粮种与仓储条件。
## 不确定性
知识库没有统一阈值。
## 来源
[E1] 低温储粮
[E2] 粮情监测"""

    response = _validate(answer, [EVIDENCE, EVIDENCE_2])

    assert response.valid is True
    assert response.citation_ids == [
        EVIDENCE_2.evidence_id,
        EVIDENCE.evidence_id,
    ]


def test_source_bibliography_rejects_operational_prose_but_stays_out_of_coverage():
    answer = """## 结论
低温能够抑制害虫活动。[E1]
## 依据
证据表明低温具有抑制作用。[E1]
## 适用条件
需结合粮种与仓储条件。
## 不确定性
知识库没有统一阈值。
## 来源
[E1] 标准规定必须在10℃通风"""

    response = _validate(answer)

    assert response.valid is False
    assert "来源条目格式无效" in response.errors
    assert response.unsupported_sentences == []
    assert response.coverage.total_sentences == 4
    assert response.coverage.cited_sentences == 2
    assert 0.0 <= response.coverage.ratio <= 1.0


def test_invalid_alias_does_not_satisfy_a_critical_claim():
    answer = """## 结论
每天检查3次。[E2]
## 依据
现有证据只提供一般说明。[E1]
## 适用条件
需结合粮种与仓储条件。
## 不确定性
知识库没有统一阈值。
## 来源
[E1] 低温储粮
[E2] 未知来源"""

    response = _validate(answer)

    assert response.valid is False
    assert "包含无效引用：E2" in response.errors
    assert "每天检查3次。[E2]" in response.unsupported_sentences
    assert response.coverage.cited_sentences == 1


def test_numeric_claim_without_citation_is_rejected():
    answer = """## 结论
温度必须保持在10℃。
## 依据
暂无。
## 适用条件
一般情况。
## 不确定性
暂无。
## 来源
暂无。"""
    response = _validate(answer)
    assert response.valid is False
    assert "温度必须保持在10℃。" in response.unsupported_sentences


def test_number_only_claim_without_citation_is_rejected():
    answer = """## 结论
每天检查3次。
## 依据
暂无。
## 适用条件
一般情况。
## 不确定性
暂无。
## 来源
暂无。"""

    response = _validate(answer)

    assert response.valid is False
    assert "每天检查3次。" in response.unsupported_sentences


def test_unit_only_claim_without_citation_is_rejected():
    answer = """## 结论
温度以℃表示。
## 依据
暂无。
## 适用条件
一般情况。
## 不确定性
暂无。
## 来源
暂无。"""

    response = _validate(answer)

    assert response.valid is False
    assert "温度以℃表示。" in response.unsupported_sentences


def test_legal_claim_without_citation_is_rejected():
    answer = """## 结论
应当依据法律执行。
## 依据
暂无。
## 适用条件
一般情况。
## 不确定性
暂无。
## 来源
暂无。"""

    response = _validate(answer)

    assert response.valid is False
    assert "应当依据法律执行。" in response.unsupported_sentences


def test_high_risk_operation_without_citation_is_rejected():
    answer = """## 结论
使用磷化铝。
## 依据
暂无。
## 适用条件
一般情况。
## 不确定性
暂无。
## 来源
暂无。"""

    response = _validate(answer)

    assert response.valid is False
    assert "使用磷化铝。" in response.unsupported_sentences


@pytest.mark.parametrize(
    "claim",
    [
        "立即执行磷\u200b化铝熏\u200b蒸。",
        "立即执行磷**化铝熏**蒸。",
        "立即执行磷_化铝熏_蒸。",
        "立即执行磷~~化铝熏~~蒸。",
        "立即执行磷`化铝熏`蒸。",
        "立即执行磷\u0338化铝熏\u0338蒸。",
        "立即执行磷　化铝熏\u2009蒸。",
    ],
)
def test_obfuscated_high_risk_operation_without_citation_is_rejected(claim):
    response = _validate(_complete_answer(claim))

    assert response.valid is False
    assert claim in response.unsupported_sentences
    assert "关键结论缺少引用" in response.errors


@pytest.mark.parametrize(
    "conclusion",
    [
        "低温储粮有助于维持粮食品质。",
        "建议结合仓型与粮种分析。",
        "立即执行磷化铝熏蒸。[E1]",
    ],
)
def test_security_canonicalization_preserves_ordinary_valid_controls(
    conclusion,
):
    response = _validate(_complete_answer(conclusion))

    assert response.valid is True
    assert response.unsupported_sentences == []


@pytest.mark.parametrize(
    "claim",
    [
        "立即执行磷<!-- hidden -->化铝熏蒸。",
        "立即执行磷<b>化铝</b>熏蒸。",
        "立即执行[磷化铝熏蒸](https://example.test)。",
        "立即执行磷&ZeroWidthSpace;化铝熏蒸。",
        "立即执行磷\u0903化铝熏蒸。",
        "立即执行磷\\化铝熏蒸。",
        "立即执行![磷化铝熏蒸](image.png)。",
        "立即执行<https://example.test/磷化铝熏蒸>。",
        "立即执行磷&#8203;化铝熏蒸。",
        "立即执行磷&#x200B;化铝熏蒸。",
    ],
)
def test_substantive_sections_reject_renderer_and_unicode_constructs(claim):
    response = _validate(_complete_answer(claim))

    assert response.valid is False
    assert "正文包含不允许的格式" in response.errors


@pytest.mark.parametrize(
    "conclusion",
    [
        "低温储粮适用于一般仓储条件，需持续观察。[E1]",
        "Storage remains stable under normal conditions.",
        "粮情稳定（仍需观察）：“继续监测”。",
    ],
)
def test_closed_substantive_format_accepts_plain_text_controls(conclusion):
    response = _validate(
        _complete_answer(
            conclusion,
            source="- [E1] 低温储粮",
        )
    )

    assert response.valid is True
    assert response.unsupported_sentences == []


def test_nfkc_category_change_u037a_is_rejected_before_critical_scanning():
    claim = "立即执行磷\u037a化铝熏\u037a蒸。"

    response = _validate(_complete_answer(claim))

    assert response.valid is False
    assert (
        "正文包含不允许的格式" in response.errors
        or claim in response.unsupported_sentences
    )


def test_nfkc_compatibility_candidates_are_closed_or_critical():
    def is_han(character: str) -> bool:
        codepoint = ord(character)
        return (
            0x3400 <= codepoint <= 0x4DBF
            or 0x4E00 <= codepoint <= 0x9FFF
            or 0xF900 <= codepoint <= 0xFAFF
            or 0x20000 <= codepoint <= 0x323AF
        )

    candidates: list[tuple[str, str]] = []
    for codepoint in range(0x110000):
        character = chr(codepoint)
        normalized = unicodedata.normalize("NFKC", character)
        category = unicodedata.category(character)
        raw_may_be_plain = (
            category[0] in {"L", "N"}
            or category == "Zs"
            or character in PLAIN_TEXT_PUNCTUATION
        )
        if (
            normalized != character
            and raw_may_be_plain
            and not is_han(character)
        ):
            candidates.append((character, normalized))

    failures = []
    normalized_han_candidates = 0
    safe_visible_boundaries = frozenset(
        "。，、；：！？.,;:!?（）()“”‘’\"'《》〈〉—–-…/"
    )
    for character, normalized in candidates:
        claim = f"磷{character}化铝熏{character}蒸。"
        closed = _has_closed_substantive_format([claim])
        if any(is_han(item) for item in normalized):
            normalized_han_candidates += 1
            if closed:
                failures.append(
                    (
                        f"U+{ord(character):04X}",
                        "introduced Han remained valid",
                        repr(normalized),
                    )
                )
            continue
        if (
            closed
            and not _is_critical(claim)
            and not (
                normalized
                and all(
                    item in safe_visible_boundaries for item in normalized
                )
            )
        ):
            failures.append(
                (
                    f"U+{ord(character):04X}",
                    unicodedata.category(character),
                    repr(normalized),
                )
            )

    assert len(candidates) == 2_752
    assert normalized_han_candidates == 27
    assert not failures, failures[:20]


def test_compatibility_space_validation_completes_within_linear_bound():
    context = multiprocessing.get_context("spawn")
    queue = context.Queue()
    process = context.Process(
        target=_check_long_compatibility_space_line,
        args=(queue,),
    )
    process.start()
    process.join(timeout=1.0)
    if process.is_alive():
        process.terminate()
        process.join()
        pytest.fail("32K compatibility-space validation exceeded 1 second")

    assert process.exitcode == 0
    assert queue.get(timeout=0.1) is True


@pytest.mark.parametrize(
    "character",
    [
        "\u3192",
        "\u3038",
        "\u3039",
        "\u303a",
        "\u3220",
        "\u3280",
        "\u32c0",
        "\U0001f229",
    ],
    ids=[
        "annotation-one",
        "hangzhou-ten",
        "hangzhou-twenty",
        "hangzhou-thirty",
        "parenthesized-ideograph",
        "circled-ideograph",
        "telegraph-month",
        "squared-ideograph",
    ],
)
def test_non_han_compatibility_characters_cannot_normalize_into_han(
    character,
):
    claim = f"原始字符{character}不得改变脚本。[E1]"

    response = _validate(_complete_answer(claim))

    assert response.valid is False
    assert "正文包含不允许的格式" in response.errors


def test_cjk_compatibility_ideograph_remains_in_the_han_security_scan():
    uncited_claim = "应依照法\uf9d8执行。"
    uncited = _validate(_complete_answer(uncited_claim))
    cited = _validate(_complete_answer(f"{uncited_claim}[E1]"))

    assert "正文包含不允许的格式" not in uncited.errors
    assert uncited_claim in uncited.unsupported_sentences
    assert cited.valid is True


@pytest.mark.parametrize("numeral", ["\u3021", "\u3025", "\u3029"])
def test_hangzhou_numerals_are_numeric_claims_without_script_rewriting(
    numeral,
):
    uncited_claim = f"仓号为{numeral}。"
    uncited = _validate(_complete_answer(uncited_claim))
    cited = _validate(_complete_answer(f"{uncited_claim}[E1]"))

    assert "正文包含不允许的格式" not in uncited.errors
    assert uncited_claim in uncited.unsupported_sentences
    assert cited.valid is True


@pytest.mark.parametrize(
    "claim",
    [
        "粮食流通、风险管理",
        "登记指标、准确记录",
        "制度办法、规范文件",
        "本方法、律例和其他资料",
    ],
)
def test_visible_boundaries_do_not_create_han_critical_terms(claim):
    response = _validate(_complete_answer(f"{claim}。"))

    assert response.valid is True
    assert response.unsupported_sentences == []


@pytest.mark.parametrize("separator", ["\n", "\r", "\r\n"])
def test_high_risk_operation_across_normal_line_break_requires_citation(
    separator,
):
    claim = f"立即通{separator}风处理。"
    response = _validate(_complete_answer(claim))

    assert response.valid is False
    assert claim.replace("\r\n", "\n").replace("\r", "\n") in (
        response.unsupported_sentences
    )


@pytest.mark.parametrize(
    "separator",
    ["\v", "\f", "\x85", "\u2028", "\u2029", "\x1c"],
)
def test_non_crlf_line_and_control_separators_are_closed(separator):
    response = _validate(_complete_answer(f"立即通{separator}风处理。[E1]"))

    assert response.valid is False
    assert "正文包含不允许的格式" in response.errors


@pytest.mark.parametrize(
    "claim",
    [
        "粮食流通风险需要持续关注。",
        "粮食流通\n风险需要持续关注。",
    ],
)
def test_line_boundaries_do_not_join_ordinary_flow_and_risk_text(claim):
    response = _validate(_complete_answer(claim))

    assert response.valid is True
    assert response.unsupported_sentences == []


@pytest.mark.parametrize(
    "claim",
    [
        "仓温为十五摄氏度。",
        "水分为百分之十三。",
        "剂量为五毫克。",
        "Use aluminum phosphide.",
        "Fumigation is required.",
        "Ventilate the granary immediately.",
        "建议对仓房通风。",
        "可通过通风降低粮温。",
        "Fumigate the granary immediately.",
        "Fumigating the granary is required.",
        "Begin ventilation immediately.",
    ],
)
def test_bilingual_structured_critical_claims_require_citations(claim):
    uncited = _validate(_complete_answer(claim))
    cited = _validate(_complete_answer(f"{claim}[E1]"))

    assert claim in uncited.unsupported_sentences
    assert cited.valid is True


@pytest.mark.parametrize(
    "claim",
    [
        "粮食流通风险需要持续关注。",
        "Aluminum products require review.",
        "The ventilation risk remains unclear.",
    ],
)
def test_bilingual_classifier_respects_word_and_operation_boundaries(claim):
    response = _validate(_complete_answer(claim))

    assert response.valid is True


@pytest.mark.parametrize(
    "claim",
    [
        "Ventilation is recommended.",
        "Ventilating grain is recommended.",
        "推荐通风。",
        "可以采用通风。",
    ],
)
def test_recommended_ventilation_forms_are_critical_and_require_citations(
    claim,
):
    assert _is_critical(claim) is True

    uncited = _validate(_complete_answer(claim))
    cited = _validate(_complete_answer(f"{claim}[E1]"))

    assert uncited.valid is False
    assert claim in uncited.unsupported_sentences
    assert "关键结论缺少引用" in uncited.errors
    assert cited.valid is True


@pytest.mark.parametrize(
    "claim",
    [
        "建议评估交通风险。",
        "The ventilation risk remains unclear.",
    ],
)
def test_ventilation_risk_statements_remain_noncritical(claim):
    assert _is_critical(claim) is False

    response = _validate(_complete_answer(claim))

    assert response.valid is True
    assert response.unsupported_sentences == []


@pytest.mark.parametrize("separator", sorted(TECHNICAL_SYMBOLS))
def test_technical_symbols_cannot_split_han_words(separator):
    response = _validate(
        _complete_answer(f"立即执行磷{separator}化铝熏蒸。[E1]")
    )

    assert response.valid is False
    assert "正文包含不允许的格式" in response.errors


@pytest.mark.parametrize(
    "claim",
    [
        "粮食/油脂仓储条件不同。[E1]",
        "颗粒·形态保持稳定。[E1]",
        "温度+湿度需要联合监测。[E1]",
    ],
)
def test_technical_symbols_between_han_are_valid_without_critical_join(claim):
    response = _validate(_complete_answer(claim))

    assert response.valid is True
    assert response.unsupported_sentences == []


@pytest.mark.parametrize(
    "claim",
    [
        "温度为15±1℃。[E1]",
        "浓度为5 μg·m⁻³。[E1]",
        "尺寸为2×3米。[E1]",
        "质量分数为5‰。[E1]",
        "温度为１５℃，浓度为５％。[E1]",
        "单位为ＰＰＭ。[E1]",
        "CO₂ concentration is stable.[E1]",
    ],
)
def test_exact_renderer_inert_technical_symbols_are_allowed(claim):
    response = _validate(_complete_answer(claim))

    assert response.valid is True
    assert response.unsupported_sentences == []


@pytest.mark.parametrize(
    "claim",
    [
        "温度为15±1℃。",
        "浓度为5 μg·m⁻³。",
        "尺寸为2×3米。",
        "质量分数为5‰。",
    ],
)
def test_uncited_technical_statements_remain_critical(claim):
    response = _validate(_complete_answer(claim))

    assert response.valid is False
    assert "正文包含不允许的格式" not in response.errors
    assert claim in response.unsupported_sentences


def test_technical_symbols_do_not_relax_renderer_controls():
    response = _validate(_complete_answer("温度为15±1℃<!-- hidden -->。[E1]"))

    assert response.valid is False
    assert "正文包含不允许的格式" in response.errors


@pytest.mark.parametrize(
    "claim",
    [
        "- 低温能够抑制害虫活动。[E1]",
        "* 低温能够抑制害虫活动。[E1]",
        "+ 低温能够抑制害虫活动。[E1]",
        "> 低温能够抑制害虫活动。[E1]",
        "1. 低温能够抑制害虫活动。[E1]",
        "1) 低温能够抑制害虫活动。[E1]",
        "---\n低温能够抑制害虫活动。[E1]",
        "===\n低温能够抑制害虫活动。[E1]",
        "    低温能够抑制害虫活动。[E1]",
    ],
)
def test_substantive_sections_reject_markdown_block_syntax(claim):
    response = _validate(_complete_answer(claim))

    assert response.valid is False
    assert "正文包含不允许的格式" in response.errors


def test_unrecognized_markdown_heading_is_not_substantive_text():
    response = _validate(
        _complete_answer("# 低温能够抑制害虫活动。[E1]")
    )

    assert response.valid is False
    assert "章节之外包含实质内容" in response.errors


@pytest.mark.parametrize(
    "claim",
    [
        "参考 https://example.test。[E1]",
        "参考 HTTP://example.test。[E1]",
        "参考 www.example.test。[E1]",
    ],
)
def test_substantive_sections_reject_bare_urls(claim):
    response = _validate(_complete_answer(claim))

    assert response.valid is False
    assert "正文包含不允许的格式" in response.errors


@pytest.mark.parametrize(
    "claim",
    [
        "参考 ftp://example.test。[E1]",
        "参考 file:///tmp/example。[E1]",
        "参考 git+ssh://example.test/repo。[E1]",
        "执行 javascript:alert(1)。[E1]",
        "内容为 data:text/plain,hello。[E1]",
        "执行 vbscript:msgbox(1)。[E1]",
        "联系 mailto:user。[E1]",
        "联系 tel:123。[E1]",
        "参考 http:/example.test。[E1]",
        "参考 https:/example.test。[E1]",
        "参考 ftp:/example.test。[E1]",
        "参考 file:/tmp/example。[E1]",
    ],
)
def test_substantive_sections_reject_arbitrary_and_dangerous_schemes(claim):
    response = _validate(_complete_answer(claim))

    assert response.valid is False
    assert "正文包含不允许的格式" in response.errors


@pytest.mark.parametrize(
    "claim",
    [
        "低温有效。[E1](relative/path)",
        "低温有效。[E1] (relative/path)",
        "低温有效。[E1]（relative/path）",
        "低温有效。[E1]　（relative/path）",
        "低温有效。[E1]: reference",
        "低温有效。[E1] ： reference",
        "[E1]: reference",
        "[E1]： reference",
    ],
)
def test_citation_tokens_cannot_open_links_or_reference_definitions(claim):
    response = _validate(_complete_answer(claim))

    assert response.valid is False
    assert "正文包含不允许的格式" in response.errors


@pytest.mark.parametrize(
    "claim",
    [
        "低温有效。[E1] 后续继续观察。",
        "URL 字样不是链接。[E1]",
        "javascript 与 data 是协议名称。[E1]",
        "custom:payload 是普通标识。[E1]",
        "1)文本说明。[E1]",
    ],
)
def test_link_and_list_words_without_link_grammar_remain_plain_text(claim):
    response = _validate(_complete_answer(claim))

    assert response.valid is True


@pytest.mark.parametrize(
    "source",
    [
        "[E1] 低温储粮",
        "- [E1] 低温储粮",
        "* [E1] 低温储粮",
        "+ [E1] 低温储粮",
        "1. [E1] 低温储粮",
    ],
)
def test_source_bibliography_markers_keep_their_separate_grammar(source):
    response = _validate(
        _complete_answer("低温能够抑制害虫活动。[E1]", source=source)
    )

    assert response.valid is True


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("title", "<script>STORED_METADATA_SENTINEL</script>"),
        ("source", "<img onerror=STORED_METADATA_SENTINEL>"),
        ("title", "[外链](javascript:STORED_METADATA_SENTINEL)"),
    ],
)
def test_stored_source_metadata_must_have_renderer_safe_grammar(field, value):
    evidence = EVIDENCE.model_copy(update={field: value})
    description = (
        evidence.title if field == "title" else evidence.source
    )
    response = _validate(
        _complete_answer(
            "低温能够抑制害虫活动。[E1]",
            source=f"[E1] {description}",
        ),
        evidences=[evidence],
    )

    assert response.valid is False
    assert "来源条目格式无效" in response.errors


@pytest.mark.parametrize(
    "claim",
    [
        "-5℃条件需结合证据。[E1]",
        "1.5℃变化需结合证据。[E1]",
        "2×3米区域需继续观察。[E1]",
        "1)文本说明。[E1]",
    ],
)
def test_negative_decimal_and_dimension_text_are_not_markdown_blocks(claim):
    response = _validate(_complete_answer(claim))

    assert response.valid is True


def test_section_names_embedded_in_prose_do_not_satisfy_required_headings():
    answer = """这里有结论、依据、适用条件、不确定性和来源。[E1]"""

    response = _validate(answer)

    assert response.valid is False
    assert "缺少必要章节：结论" in response.errors


def test_malformed_citation_alias_is_rejected_alongside_valid_citation():
    answer = """## 结论
低温能够抑制害虫活动。[E1][X1]
## 依据
证据表明低温具有抑制作用。[E1]
## 适用条件
需结合粮种与仓储条件。
## 不确定性
知识库未提供统一温度阈值。
## 来源
[E1] 低温储粮 [Efoo]"""

    response = _validate(answer)

    assert response.valid is False
    assert "包含无效引用：Efoo, X1" in response.errors


def test_hyphenated_and_underscored_citation_aliases_are_rejected():
    answer = """## 结论
低温能够抑制害虫活动。[E1][E-foo]
## 依据
证据表明低温具有抑制作用。[E1]
## 适用条件
需结合粮种与仓储条件。
## 不确定性
知识库未提供统一温度阈值。
## 来源
[E1] 低温储粮 [E_foo]"""

    response = _validate(answer)

    assert response.valid is False
    assert "包含无效引用：E-foo, E_foo" in response.errors
