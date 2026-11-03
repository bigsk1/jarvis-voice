"""Private, offline PDF rendering using the fonts shipped with Jarvis.

Markdown images are displayed as references, never loaded. Ordinary links and
private text are preserved; this module does not apply public-sharing filters.
"""

from pathlib import Path
from typing import cast
from urllib.parse import urlsplit

from fpdf import FPDF
from markdown_it import MarkdownIt
from markdown_it.token import Token

MAX_SOURCE_BYTES = 5 * 1024 * 1024
FONT_DIR = Path(__file__).resolve().parents[1] / "jarvis-web" / "client" / "fonts"


def check_pdf_source(text: str) -> None:
    if not isinstance(text, str):
        raise ValueError("PDF source must be text")
    if len(text.encode("utf-8")) > MAX_SOURCE_BYTES:
        raise ValueError("PDF text source exceeds the 5 MiB limit; no content was converted")


def read_pdf_text_source(path: str | Path) -> str:
    """Read the complete UTF-8 source or fail explicitly instead of truncating."""
    with open(path, "rb") as source:
        content = source.read(MAX_SOURCE_BYTES + 1)
    if len(content) > MAX_SOURCE_BYTES:
        raise ValueError("PDF text source exceeds the 5 MiB limit; no content was converted")
    return content.decode("utf-8-sig")


def register_pdf_fonts(pdf: FPDF) -> None:
    regular = FONT_DIR / "InterVariable.woff2"
    italic = FONT_DIR / "Inter-Italic.woff2"
    for style, path, variations in (
        ("", regular, {"wght": 400, "opsz": 14}),
        ("B", regular, {"wght": 680, "opsz": 22}),
        ("I", italic, None),
        ("BI", italic, None),
    ):
        # fpdf2 >=2.8.8 supports variable fonts; older bundled type stubs do not.
        pdf.add_font("Inter", style, str(path), variations=variations)  # pyrefly: ignore[unexpected-keyword]
    for style, suffix in (("", "Regular"), ("B", "Bold"), ("I", "Italic"), ("BI", "BoldItalic")):
        pdf.add_font("JetBrainsMono", style, str(FONT_DIR / f"JetBrainsMono-{suffix}.woff2"))


class DocumentPDF(FPDF):
    """Unicode document shell shared by plain, mixed, and Markdown creation."""

    def __init__(self, title: str = "Document"):
        super().__init__()
        self.render_warnings: list[str] = []
        self._missing_characters: set[int] = set()
        self.doc_title = title
        self.set_margins(16, 16, 16)
        self.set_auto_page_break(auto=True, margin=16)
        register_pdf_fonts(self)
        self.set_title(title)
        self.set_creator("Jarvis")

    def clean_text(self, text: str, family: str = "Inter", style: str = "") -> str:
        """Replace unsupported glyphs visibly and report them, without dropping text."""
        cmap = self.fonts[family.lower() + style].cmap
        result = []
        for character in text.replace("\r\n", "\n").replace("\r", "\n"):
            code = ord(character)
            if character in "\n\t" or code in cmap:
                result.append(character)
            else:
                self._missing_characters.add(code)
                result.append(f"[U+{code:04X}]")
        return "".join(result)

    def footer(self):
        self.set_y(-12)
        self.set_font("Inter", "", 8)
        self.set_text_color(110, 110, 110)
        self.cell(0, 6, f"Page {self.page_no()}", align="C")

    def add_title(self, title: str):
        self.set_font("Inter", "B", 23)
        self.set_text_color(25, 30, 40)
        self.set_x(self.l_margin)
        self.multi_cell(0, 11, self.clean_text(title, style="B"), new_x="LMARGIN", new_y="NEXT")
        self.ln(5)

    def add_heading(self, text: str, level: int = 1):
        size = {1: 19, 2: 16, 3: 13}.get(level, 11)
        self.set_font("Inter", "B", size)
        self.set_text_color(35, 40, 50)
        self.ln(3)
        self.set_x(self.l_margin)
        self.multi_cell(0, size * 0.48, self.clean_text(text, style="B"), new_x="LMARGIN", new_y="NEXT")
        self.ln(2)

    def add_text(self, text: str):
        self.set_font("Inter", "", 10.5)
        self.set_text_color(20, 25, 30)
        self.set_x(self.l_margin)
        self.multi_cell(0, 5.4, self.clean_text(text).expandtabs(4), new_x="LMARGIN", new_y="NEXT")
        self.ln(3)

    def add_code(self, text: str):
        self.set_font("JetBrainsMono", "", 8.5)
        self.set_text_color(30, 35, 45)
        self.set_fill_color(242, 244, 247)
        self.set_x(self.l_margin)
        self.multi_cell(
            0, 4.5, self.clean_text(text, "JetBrainsMono").expandtabs(4).rstrip("\n"),
            fill=True, wrapmode="CHAR", new_x="LMARGIN", new_y="NEXT", padding=2,
        )
        self.ln(3)

    def warnings(self) -> list[str]:
        result = list(self.render_warnings)
        if self._missing_characters:
            codes = sorted(self._missing_characters)
            listed = ", ".join(f"U+{code:04X}" for code in codes[:20])
            if len(codes) > 20:
                listed += f", and {len(codes) - 20} other code points"
            result.append(f"Bundled fonts lack {listed}; visible [U+XXXX] placeholders preserve their positions.")
        return result


def _visible_inline(tokens: list[Token]) -> str:
    """Flatten table inline formatting without losing its link destinations."""
    parts = []
    links = []
    for token in tokens:
        if token.type == "link_open":
            links.append(token.attrGet("href") or "")
        elif token.type == "link_close" and links:
            parts.append(f" ({links.pop()})")
        elif token.type == "image":
            parts.append(f"[Image: {token.content}; {token.attrGet('src') or ''}]")
        elif token.type in {"softbreak", "hardbreak"}:
            parts.append("\n")
        elif token.type in {"text", "code_inline", "html_inline"}:
            parts.append(token.content)
    return "".join(parts)


def _clickable_link(target: str) -> bool:
    try:
        return urlsplit(target).scheme.lower() in {"http", "https", "mailto"}
    except ValueError:
        return False


def _write_inline(pdf: DocumentPDF, tokens: list[Token], *, level: int = 0, indent: float = 0, bullet: str = "", quote: bool = False):
    size = {1: 19, 2: 16, 3: 13}.get(level, 11 if level else 10.5)
    bold, italic, strike = bool(level), quote, False
    links: list[str] = []
    pdf.set_x(pdf.l_margin)
    pdf.set_text_color(20, 25, 30)
    # Paragraphs capture their marker font when opened, before inline runs.
    pdf.set_font("Inter", ("B" if bold else "") + ("I" if italic else ""), size)
    pdf.strikethrough = False
    with pdf.text_columns(line_height=1.35, wrapmode="WORD") as columns:
        with columns.paragraph(top_margin=3 if level else 0, bottom_margin=2.5, indent=indent, bullet_string=bullet) as paragraph:
            for token in tokens:
                if token.type in {"strong_open", "strong_close"}:
                    bold = token.type == "strong_open" or bool(level)
                    continue
                if token.type in {"em_open", "em_close"}:
                    italic = token.type == "em_open" or quote
                    continue
                if token.type in {"s_open", "s_close"}:
                    strike = token.type == "s_open"
                    continue
                if token.type == "link_open":
                    links.append(token.attrGet("href") or "")
                    continue
                if token.type == "link_close":
                    if links:
                        target = links.pop()
                        if target and not _clickable_link(target):
                            pdf.set_font("Inter", "", size)
                            pdf.set_text_color(20, 25, 30)
                            paragraph.write(pdf.clean_text(f" ({target})"))
                    continue
                if token.type in {"softbreak", "hardbreak"}:
                    text = " " if token.type == "softbreak" else "\n"
                elif token.type == "image":
                    text = f"[Image: {token.content or 'image'}; {token.attrGet('src') or ''}]"
                    warning = "Markdown images are shown as text references; no image URLs or local files were loaded."
                    if warning not in pdf.render_warnings:
                        pdf.render_warnings.append(warning)
                elif token.type in {"text", "code_inline", "html_inline"}:
                    text = token.content
                else:
                    continue
                family = "JetBrainsMono" if token.type == "code_inline" else "Inter"
                style = ("B" if bold else "") + ("I" if italic else "")
                target = links[-1] if links else ""
                link = target if _clickable_link(target) else None
                pdf.set_font(family, style + ("U" if link else ""), size - (1 if family == "JetBrainsMono" else 0))
                pdf.strikethrough = strike
                pdf.set_text_color(*(25, 85, 165) if link else (20, 25, 30))
                cleaned = pdf.clean_text(text, family, style)
                if family == "Inter" and style == "BI":
                    # The bundled italic face is static weight 400. Paragraph
                    # fragments capture this local state; later text stays fill-only.
                    saved = pdf.text_mode, pdf.line_width, pdf.draw_color
                    try:
                        pdf.text_mode = "FILL_STROKE"
                        pdf.line_width = 0.07
                        pdf.draw_color = pdf.text_color
                        paragraph.write(cleaned, link=link)
                    finally:
                        pdf.text_mode, pdf.line_width, pdf.draw_color = saved
                else:
                    paragraph.write(cleaned, link=link)
    pdf.strikethrough = False


def _write_table(pdf: DocumentPDF, tokens: list[Token]):
    rows: list[list[str]] = []
    for token in tokens:
        if token.type == "tr_open":
            rows.append([])
        elif token.type == "inline" and rows:
            rows[-1].append(_visible_inline(token.children or []))
    if not rows or not rows[0]:
        return
    columns = max(map(len, rows))
    pdf.set_font("Inter", "", 9)
    pdf.set_text_color(20, 25, 30)
    cleaned = [[pdf.clean_text(cell) for cell in row] for row in rows]
    width = pdf.epw / columns
    tall = columns > 6 or width < 22
    if not tall:
        for row in cleaned:
            for cell in row:
                height = cast(float, pdf.multi_cell(width - 4, 4.8, cell, dry_run=True, output="HEIGHT"))
                if height > 150:
                    tall = True
                    break
            if tall:
                break
    if tall:
        pdf.render_warnings.append("A wide or tall Markdown table was rendered as labeled rows to preserve all cell content.")
        for index, row in enumerate(cleaned[1:], 1):
            pdf.add_heading(f"Table row {index}", 3)
            for column, cell in enumerate(row):
                label = cleaned[0][column] if column < len(cleaned[0]) else f"Column {column + 1}"
                pdf.add_text(f"{label}: {cell}")
        if len(cleaned) == 1:
            for cell in cleaned[0]:
                pdf.add_text(cell)
        return
    pdf.set_x(pdf.l_margin)
    with pdf.table(text_align="LEFT", line_height=4.8, padding=2, width=pdf.epw, wrapmode="WORD") as table:
        for row in cleaned:
            cells = table.row()
            for cell in row + [""] * (columns - len(row)):
                cells.cell(cell)
    pdf.ln(3)


def write_markdown(pdf: DocumentPDF, markdown: str) -> None:
    """Append formatted Markdown; token rendering cannot load image resources."""
    check_pdf_source(markdown)
    renderer = MarkdownIt("commonmark", {"html": False, "linkify": True})
    renderer.enable(["linkify", "strikethrough", "table"])
    tokens = renderer.parse(markdown)
    lists: list[dict] = []
    pending_bullet = ""
    quote_depth = 0
    level = 0
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token.type == "heading_open":
            level = int(token.tag[1:])
        elif token.type == "heading_close":
            level = 0
        elif token.type in {"bullet_list_open", "ordered_list_open"}:
            lists.append({"ordered": token.type == "ordered_list_open", "next": int(token.attrGet("start") or 1)})
        elif token.type in {"bullet_list_close", "ordered_list_close"}:
            lists.pop()
        elif token.type == "list_item_open" and lists:
            current = lists[-1]
            pending_bullet = f"{current['next']}." if current["ordered"] else "•"
            current["next"] += 1
        elif token.type == "list_item_close":
            pending_bullet = ""
        elif token.type == "blockquote_open":
            quote_depth += 1
        elif token.type == "blockquote_close":
            quote_depth -= 1
        elif token.type == "inline":
            indent = min(45, len(lists) * 6 + quote_depth * 5)
            _write_inline(pdf, token.children or [], level=level, indent=indent, bullet=pending_bullet, quote=bool(quote_depth))
            pending_bullet = ""
        elif token.type in {"fence", "code_block"}:
            pdf.add_code(token.content)
        elif token.type == "table_open":
            end = index + 1
            while end < len(tokens) and tokens[end].type != "table_close":
                end += 1
            table_tokens = tokens[index:end]
            if any(child.type == "image" for item in table_tokens for child in (item.children or [])):
                pdf.render_warnings.append("Markdown table images are shown as text references; no resources were loaded.")
            _write_table(pdf, table_tokens)
            index = end
        elif token.type == "hr":
            pdf.set_draw_color(180, 185, 190)
            pdf.line(pdf.l_margin, pdf.get_y() + 2, pdf.w - pdf.r_margin, pdf.get_y() + 2)
            pdf.ln(5)
        index += 1


def _render_pdf(text: str, output_path: str, title: str, *, markdown: bool) -> dict:
    check_pdf_source(text)
    check_pdf_source(title)
    pdf = DocumentPDF(title)
    pdf.add_page()
    pdf.add_title(title)
    if markdown:
        write_markdown(pdf, text)
    else:
        pdf.add_text(text)
    pdf.output(output_path)
    return {"page_count": pdf.page_no(), "warnings": pdf.warnings()}


def render_markdown_pdf(markdown: str, output_path: str, title: str = "Document") -> dict:
    return _render_pdf(markdown, output_path, title, markdown=True)


def render_text_pdf(text: str, output_path: str, title: str = "Document") -> dict:
    return _render_pdf(text, output_path, title, markdown=False)
