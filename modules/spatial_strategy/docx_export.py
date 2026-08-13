from __future__ import annotations

import re
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt


_IMAGE_RE = re.compile(r"^!\[([^]]*)\]\(([^)]+)\)$")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_BULLET_RE = re.compile(r"^\s*[-*+]\s+(.+?)\s*$")
_NUMBER_RE = re.compile(r"^\s*\d+[.)]\s+(.+?)\s*$")


def _set_font(style, name: str = "Microsoft YaHei", size: int = 10) -> None:
    style.font.name = name
    style.font.size = Pt(size)
    rpr = style._element.get_or_add_rPr()
    fonts = rpr.rFonts
    if fonts is None:
        fonts = OxmlElement("w:rFonts")
        rpr.append(fonts)
    fonts.set(qn("w:eastAsia"), name)


def _add_page_number(paragraph) -> None:
    run = paragraph.add_run()
    field_begin = OxmlElement("w:fldChar")
    field_begin.set(qn("w:fldCharType"), "begin")
    instruction = OxmlElement("w:instrText")
    instruction.set(qn("xml:space"), "preserve")
    instruction.text = "PAGE"
    field_end = OxmlElement("w:fldChar")
    field_end.set(qn("w:fldCharType"), "end")
    run._r.extend((field_begin, instruction, field_end))


def _add_table(document: Document, rows: list[list[str]]) -> None:
    if not rows:
        return
    width = max(len(row) for row in rows)
    table = document.add_table(rows=1, cols=width)
    table.style = "Light Shading Accent 1"
    for index, value in enumerate(rows[0]):
        table.rows[0].cells[index].text = value.strip()
    for row in rows[2:] if len(rows) > 1 and all(set(cell.strip()) <= {"-", ":", " "} for cell in rows[1]) else rows[1:]:
        cells = table.add_row().cells
        for index, value in enumerate(row):
            cells[index].text = value.strip()


def _resolve_image(base_dir: Path, raw_path: str) -> Path | None:
    path = Path(raw_path.strip())
    candidate = (base_dir / path).resolve() if not path.is_absolute() else path.resolve()
    return candidate if candidate.is_file() else None


def write_markdown_docx(markdown_path: Path, output_path: Path, *, title: str = "") -> Path:
    """Render the report markdown into a readable Word document."""
    markdown = markdown_path.read_text(encoding="utf-8")
    document = Document()
    section = document.sections[0]
    section.top_margin = Inches(0.7)
    section.bottom_margin = Inches(0.7)
    section.left_margin = Inches(0.85)
    section.right_margin = Inches(0.85)
    _set_font(document.styles["Normal"], size=10)
    for style_name, size in (("Title", 20), ("Heading 1", 15), ("Heading 2", 12), ("Heading 3", 11)):
        _set_font(document.styles[style_name], size=size)

    footer = section.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    footer.add_run("第 ")
    _add_page_number(footer)
    footer.add_run(" 页")

    lines = markdown.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        if not line:
            index += 1
            continue
        image_match = _IMAGE_RE.match(line)
        if image_match:
            image_path = _resolve_image(markdown_path.parent, image_match.group(2))
            if image_path:
                paragraph = document.add_paragraph()
                paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
                paragraph.add_run().add_picture(str(image_path), width=Inches(6.1))
                caption = document.add_paragraph(image_match.group(1))
                caption.alignment = WD_ALIGN_PARAGRAPH.CENTER
                caption.style = "Caption"
            index += 1
            continue
        heading_match = _HEADING_RE.match(line)
        if heading_match:
            level = min(len(heading_match.group(1)), 3)
            text = heading_match.group(2).strip()
            if level == 1 and not document.paragraphs:
                document.add_paragraph(text, style="Title")
            else:
                document.add_paragraph(text, style=f"Heading {level}")
            index += 1
            continue
        if line.startswith("|"):
            rows = []
            while index < len(lines) and lines[index].strip().startswith("|"):
                rows.append([cell for cell in lines[index].strip().strip("|").split("|")])
                index += 1
            _add_table(document, rows)
            continue
        bullet_match = _BULLET_RE.match(line)
        if bullet_match:
            document.add_paragraph(bullet_match.group(1), style="List Bullet")
            index += 1
            continue
        number_match = _NUMBER_RE.match(line)
        if number_match:
            document.add_paragraph(number_match.group(1), style="List Number")
            index += 1
            continue
        if line in {"---", "***"}:
            index += 1
            continue
        document.add_paragraph(line)
        index += 1

    if title and not document.paragraphs:
        document.add_paragraph(title, style="Title")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    document.save(output_path)
    return output_path
