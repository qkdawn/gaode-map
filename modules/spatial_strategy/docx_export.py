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
_NUMBER_RE = re.compile(r"^\s*(\d+)[.)]\s+(.+?)\s*$")
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")


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


def _set_document_zoom(document: Document, percent: int = 100) -> None:
    settings = document.settings.element
    zoom = settings.find(qn("w:zoom"))
    if zoom is None:
        zoom = OxmlElement("w:zoom")
        settings.insert(0, zoom)
    zoom.set(qn("w:val"), "bestFit")
    zoom.set(qn("w:percent"), str(percent))


def _add_inline_markdown(paragraph, text: str) -> None:
    cursor = 0
    for match in _BOLD_RE.finditer(text):
        if match.start() > cursor:
            paragraph.add_run(text[cursor : match.start()])
        paragraph.add_run(match.group(1)).bold = True
        cursor = match.end()
    if cursor < len(text):
        paragraph.add_run(text[cursor:])


def _new_numbering_id(document: Document, *, start: int) -> int:
    numbering = document.part.numbering_part.element
    style_num_id = document.styles["List Number"]._element.pPr.numPr.numId.val
    style_numbering = next(
        item for item in numbering.findall(qn("w:num"))
        if int(item.get(qn("w:numId"))) == int(style_num_id)
    )
    abstract_num_id = style_numbering.find(qn("w:abstractNumId")).get(qn("w:val"))
    num_id = max(int(item.get(qn("w:numId"))) for item in numbering.findall(qn("w:num"))) + 1
    number = OxmlElement("w:num")
    number.set(qn("w:numId"), str(num_id))
    abstract = OxmlElement("w:abstractNumId")
    abstract.set(qn("w:val"), abstract_num_id)
    number.append(abstract)
    level_override = OxmlElement("w:lvlOverride")
    level_override.set(qn("w:ilvl"), "0")
    start_override = OxmlElement("w:startOverride")
    start_override.set(qn("w:val"), str(start))
    level_override.append(start_override)
    number.append(level_override)
    numbering.append(number)
    return num_id


def _add_numbered_paragraph(document: Document, text: str, *, num_id: int) -> None:
    paragraph = document.add_paragraph(style="List Number")
    num_pr = paragraph._p.get_or_add_pPr().get_or_add_numPr()
    num_pr.get_or_add_ilvl().val = 0
    num_pr.get_or_add_numId().val = num_id
    _add_inline_markdown(paragraph, text)


def _set_table_row_pagination(row, *, repeat_header: bool = False) -> None:
    properties = row._tr.get_or_add_trPr()
    cant_split = OxmlElement("w:cantSplit")
    properties.append(cant_split)
    if repeat_header:
        header = OxmlElement("w:tblHeader")
        header.set(qn("w:val"), "true")
        properties.append(header)


def _add_table(document: Document, rows: list[list[str]]) -> None:
    if not rows:
        return
    width = max(len(row) for row in rows)
    table = document.add_table(rows=1, cols=width)
    table.style = "Light Shading Accent 1"
    _set_table_row_pagination(table.rows[0], repeat_header=True)
    for index, value in enumerate(rows[0]):
        cell = table.rows[0].cells[index]
        cell.text = ""
        _add_inline_markdown(cell.paragraphs[0], value.strip())
    for row in rows[2:] if len(rows) > 1 and all(set(cell.strip()) <= {"-", ":", " "} for cell in rows[1]) else rows[1:]:
        cells = table.add_row().cells
        _set_table_row_pagination(table.rows[-1])
        for index, value in enumerate(row):
            cells[index].text = ""
            _add_inline_markdown(cells[index].paragraphs[0], value.strip())


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
    _set_document_zoom(document)
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
    active_numbering_id: int | None = None
    expected_number: int | None = None
    while index < len(lines):
        line = lines[index].strip()
        if not line:
            index += 1
            continue
        image_match = _IMAGE_RE.match(line)
        if image_match:
            active_numbering_id = expected_number = None
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
            active_numbering_id = expected_number = None
            level = min(len(heading_match.group(1)), 3)
            text = heading_match.group(2).strip()
            if level == 1 and not document.paragraphs:
                document.add_paragraph(text, style="Title")
            else:
                document.add_paragraph(text, style=f"Heading {level}")
            index += 1
            continue
        if line.startswith("|"):
            active_numbering_id = expected_number = None
            rows = []
            while index < len(lines) and lines[index].strip().startswith("|"):
                rows.append([cell for cell in lines[index].strip().strip("|").split("|")])
                index += 1
            _add_table(document, rows)
            continue
        bullet_match = _BULLET_RE.match(line)
        if bullet_match:
            active_numbering_id = expected_number = None
            paragraph = document.add_paragraph(style="List Bullet")
            _add_inline_markdown(paragraph, bullet_match.group(1))
            index += 1
            continue
        number_match = _NUMBER_RE.match(line)
        if number_match:
            number = int(number_match.group(1))
            if active_numbering_id is None or expected_number != number:
                active_numbering_id = _new_numbering_id(document, start=number)
            _add_numbered_paragraph(document, number_match.group(2), num_id=active_numbering_id)
            expected_number = number + 1
            index += 1
            continue
        if line in {"---", "***"}:
            active_numbering_id = expected_number = None
            index += 1
            continue
        active_numbering_id = expected_number = None
        paragraph = document.add_paragraph()
        _add_inline_markdown(paragraph, line)
        index += 1

    if title and not document.paragraphs:
        document.add_paragraph(title, style="Title")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    document.save(output_path)
    return output_path
