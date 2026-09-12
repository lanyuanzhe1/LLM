"""把智能体生成的演示文案（markdown 风格）转成 .pptx 文件。

解析规则（简单够用，面向"生成文案 → 一键导出"的演示场景）：
- 首个 `# ` 标题或 title 参数 → 标题页标题
- `## ` / `### ` → 新内容页标题
- 其余非空行（去掉 `- `、`* `、`**`、数字序号前缀）→ 该页要点
- 首个 `## ` 之前的散行视为智能体寒暄/前言，丢弃；全文无 `## ` 时全部行进一页
- 单页要点超过 MAX_BULLETS_PER_SLIDE 自动分页（标题加"（续）"），防止文字溢出
"""
import re
from io import BytesIO

from pptx import Presentation
from pptx.enum.text import MSO_AUTO_SIZE

MAX_BULLETS_PER_SLIDE = 8
# 单页正文字符数上限：默认 18pt 字号下超出会溢出文本框，按字符数分页（CJK 按 1 字符计）
MAX_CHARS_PER_SLIDE = 180

_HEADING1 = re.compile(r"^#\s+")
_HEADING = re.compile(r"^#{2,6}\s+")
_BULLET = re.compile(r"^(?:[-*•·]+|\d+[.、)）])\s*")
_DECK_TITLE = re.compile(r"^(?:主标题|标题|题目)\s*[:：]\s*(.+)$")


def _clean(line: str) -> str:
    return _BULLET.sub("", line.strip()).replace("**", "").strip()


def _paginate(bullets: list[str]) -> list[list[str]]:
    """把要点按条数和字符数双重上限分页，防止长文溢出文本框。"""
    pages: list[list[str]] = []
    current: list[str] = []
    chars = 0
    for bullet in bullets:
        if current and (len(current) >= MAX_BULLETS_PER_SLIDE or chars + len(bullet) > MAX_CHARS_PER_SLIDE):
            pages.append(current)
            current, chars = [], 0
        current.append(bullet)
        chars += len(bullet)
    if current:
        pages.append(current)
    return pages or [[]]


def parse_deck(text: str, title: str | None = None) -> tuple[str, list[tuple[str, list[str]]], bool]:
    """把文案解析为 (标题页标题, [(小节标题, [要点])], 是否真分节)。

    is_deck=False 表示文案没有 `## ` 分节标题（如智能体在反问/寒暄而非产出大纲），
    调用方应避免把这类内容当成演示文稿。
    """
    lines = [raw.strip() for raw in text.splitlines() if raw.strip()]
    has_sections = any(_HEADING.match(line) for line in lines)

    deck_title = title or "演示文稿"
    slides: list[tuple[str, list[str]]] = []  # (标题, [要点])
    current: tuple[str, list[str]] | None = None
    preamble: list[str] = []

    for line in lines:
        if _HEADING1.match(line):
            deck_title = _HEADING1.sub("", line).strip() or deck_title
            continue
        if _HEADING.match(line):
            current = (_HEADING.sub("", line).strip(), [])
            slides.append(current)
            continue
        bullet = _clean(line)
        if not bullet:
            continue
        if current is not None:
            current[1].append(bullet)
        elif has_sections:
            preamble.append(bullet)  # 标题页之前、分节之前的散行：前言，不进正文
        else:
            current = ("内容", [])
            slides.append(current)
            current[1].append(bullet)

    if title is None and deck_title == "演示文稿" and preamble:
        deck_title = preamble[0]

    if title is None:
        # 「标题：xxx」要点做标题页标题（比智能体名合适）：封面小节优先，其次任意小节
        ordered = sorted(enumerate(slides), key=lambda kv: (("封面" not in kv[1][0]), kv[0]))
        for _i, (_heading, bullets) in ordered:
            for bullet in bullets:
                match = _DECK_TITLE.match(bullet)
                if match:
                    return match.group(1).strip(), slides, has_sections

    return deck_title, slides, has_sections


def paginate_sections(slides: list[tuple[str, list[str]]]) -> list[tuple[str, list[str]]]:
    """按分页规则展开为 [(页标题, [要点])]，与 pptx 实际分页保持一致；空要点小节直接跳过。"""
    pages: list[tuple[str, list[str]]] = []
    for heading, bullets in slides:
        if not bullets:
            continue
        for page, chunk in enumerate(_paginate(bullets)):
            pages.append((heading if page == 0 else f"{heading}（续）", chunk))
    return pages


def build_pptx(text: str, title: str | None = None) -> bytes:
    """把文案转成 pptx 字节流。text 为空时抛出 ValueError。"""
    deck_title, slides, _has_sections = parse_deck(text, title)

    prs = Presentation()

    first = prs.slides.add_slide(prs.slide_layouts[0])
    first.shapes.title.text = deck_title
    if first.placeholders and len(first.placeholders) > 1:
        first.placeholders[1].text = "由智能体生成"

    for heading, chunk in paginate_sections(slides):
        slide = prs.slides.add_slide(prs.slide_layouts[1])
        slide.shapes.title.text = heading
        body = slide.placeholders[1].text_frame
        body.clear()
        body.word_wrap = True
        body.auto_size = MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE
        for index, bullet in enumerate(chunk):
            paragraph = body.paragraphs[0] if index == 0 else body.add_paragraph()
            paragraph.text = bullet

    buffer = BytesIO()
    prs.save(buffer)
    return buffer.getvalue()
