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


def build_pptx(text: str, title: str | None = None) -> bytes:
    """把文案转成 pptx 字节流。text 为空时抛出 ValueError。"""
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

    prs = Presentation()

    first = prs.slides.add_slide(prs.slide_layouts[0])
    first.shapes.title.text = deck_title
    if first.placeholders and len(first.placeholders) > 1:
        first.placeholders[1].text = "由智能体生成"

    for heading, bullets in slides:
        for page, chunk in enumerate(_paginate(bullets)):
            slide = prs.slides.add_slide(prs.slide_layouts[1])
            slide.shapes.title.text = heading if page == 0 else f"{heading}（续）"
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
