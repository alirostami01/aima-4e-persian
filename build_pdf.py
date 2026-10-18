#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build the complete AIMA Persian book PDF from the chapter HTML files."""

from __future__ import annotations

import argparse
import io
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from bs4 import BeautifulSoup
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, DictionaryObject, FloatObject, NameObject, NumberObject
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from weasyprint import HTML

ROOT = Path(__file__).resolve().parent
HTML_DIR = ROOT / "html"
PDF_DIR = ROOT / "pdf"
DEFAULT_OUTPUT = PDF_DIR / "aima-4e-persian.pdf"
CHAPTER_RE = re.compile(r"^(?P<number>\d+)-(?P<title>.+)\.html$")

REMOVE_SELECTORS = (
    ".kicker", "nav.toc", ".footer-nav", ".top-link",
    ".web-only", ".screen-only", ".print-hidden",
)

PRINT_CSS = r"""
@page { size: A4; margin: 18mm 17mm 20mm 17mm; }
html, body {
    print-color-adjust: exact !important;
    -webkit-print-color-adjust: exact !important;
}
@media print {
    .kicker, nav.toc, .footer-nav, .top-link,
    .web-only, .screen-only, .print-hidden { display: none !important; }
    .box, .tip, .warn, .ok, .formula, .note, .quote, .ex,
    .summary-box, figure, pre, table, tr, img {
        break-inside: avoid; page-break-inside: avoid;
    }
    thead { display: table-header-group; }
    p, li { orphans: 3; widows: 3; text-align: justify; text-justify: inter-word; }
}
"""


def discover_chapters() -> list[tuple[int, Path]]:
    chapters = []
    for path in HTML_DIR.glob("*.html"):
        m = CHAPTER_RE.match(path.name)
        if m:
            chapters.append((int(m.group("number")), path))
    chapters.sort(key=lambda x: x[0])
    expected = list(range(29))
    actual = [n for n, _ in chapters]
    if actual != expected:
        raise SystemExit(f"Chapter validation failed. Expected 00..28, found: {actual}")
    return chapters


def chapter_title(path: Path) -> str:
    soup = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")
    node = soup.select_one(".subtitle") or soup.title
    if node:
        text = node.get_text(" ", strip=True)
        if text:
            return text
    m = CHAPTER_RE.match(path.name)
    return m.group("title") if m else path.stem


def clean_html(path: Path) -> str:
    soup = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")
    for selector in REMOVE_SELECTORS:
        for node in soup.select(selector):
            node.decompose()

    for node in list(soup.find_all(string=True)):
        text = str(node)
        if "این صفحه از ترجمهٔ فارسی فصل‌های کتاب" in text and "راسل" in text and "نورویگ" in text:
            if node.parent:
                node.parent.decompose()

    for anchor in soup.find_all("a"):
        href = anchor.get("href", "")
        if isinstance(href, str) and href.startswith("file://"):
            anchor["href"] = "#"

    for script in soup.find_all("script"):
        script.decompose()

    style = soup.new_tag("style")
    style.string = PRINT_CSS
    if soup.head:
        soup.head.append(style)
    elif soup.html:
        head = soup.new_tag("head")
        head.append(style)
        soup.html.insert(0, head)
    return str(soup)


def render_chapters(chapters: list[tuple[int, Path]], temp_dir: Path):
    rendered = []
    for index, (number, path) in enumerate(chapters, 1):
        print(f"[{index:02d}/{len(chapters):02d}] {path.name}")
        output = temp_dir / f"chapter-{number:02d}.pdf"
        HTML(string=clean_html(path), base_url=str(path.parent)).write_pdf(str(output))
        pages = len(PdfReader(str(output)).pages)
        if pages <= 0:
            raise RuntimeError(f"Chapter {number:02d} produced an empty PDF")
        print(f"       → {pages} pages")
        rendered.append((number, chapter_title(path), output, pages))
    return rendered


def find_font() -> str | None:
    """Find a Unicode font that can be explicitly embedded in the TOC."""
    patterns = (
        "Noto Sans Arabic:style=Regular",
        "Noto Sans:style=Regular",
        "DejaVu Sans:style=Book",
    )
    for pattern in patterns:
        try:
            result = subprocess.run(
                ["fc-match", "-f", "%{file}", pattern],
                check=True,
                capture_output=True,
                text=True,
            )
            candidate = Path(result.stdout.strip())
            if candidate.exists():
                return str(candidate)
        except (FileNotFoundError, subprocess.CalledProcessError):
            pass

    for candidate in (
        "/usr/share/fonts/truetype/noto/NotoSansArabic-Regular.ttf",
        "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansArabic-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ):
        if Path(candidate).exists():
            return candidate
    return None


def make_toc_pdf(entries: list[tuple[int, str, int]], output: Path, font_path: str | None):
    """Render the Persian TOC and return its page count and row rectangles."""
    if not font_path:
        raise RuntimeError(
            "No Unicode font was found for the Persian TOC. Install Noto Sans "
            "or DejaVu Sans and run the build again."
        )

    rows = []
    for number, title, page_number in entries:
        rows.append(
            f'<div class="toc-row">'
            f'<span class="toc-title" dir="rtl"><bdi>{number:02d}. {escape_html(title)}</bdi></span>'
            f'<span class="toc-dots"></span>'
            f'<span class="toc-page" dir="ltr">{page_number}</span>'
            f'</div>'
        )

    font_face = Path(font_path).as_uri()
    html = f"""<!doctype html>
<html lang="fa" dir="rtl">
<head>
<meta charset="utf-8">
<style>
@font-face {{
  font-family: AIMA-Persian;
  src: url('{font_face}');
  font-weight: 400;
}}
@page {{ size: A4; margin: 15mm 17mm 16mm 17mm; }}
* {{ box-sizing: border-box; }}
html, body {{ margin: 0; padding: 0; direction: rtl; }}
body {{
  font-family: AIMA-Persian, "Noto Sans Arabic", "DejaVu Sans", sans-serif;
  font-size: 10pt;
  line-height: 1.2;
  direction: rtl;
  color: #222;
}}
.header {{ height: 58pt; margin: 0; text-align: center; }}
.header h1 {{ margin: 0 0 5pt; font-size: 19pt; line-height: 23pt; font-weight: 700; }}
.header p {{ margin: 0; font-size: 9pt; line-height: 11pt; }}
.toc-list {{ margin: 0; padding: 0; }}
.toc-row {{ height: 21pt; page-break-inside: avoid; display: flex; align-items: center; direction: rtl; }}
.toc-title {{ flex: 0 1 auto; white-space: nowrap; direction: rtl; unicode-bidi: isolate; }}
.toc-dots {{ flex: 1 1 auto; min-width: 10pt; border-bottom: 1px dotted #888; margin: 0 8pt 3pt; }}
.toc-page {{ flex: 0 0 28pt; direction: ltr; unicode-bidi: isolate; text-align: left; }}
</style>
</head>
<body>
<div class="header">
  <h1 dir="rtl">فهرست مطالب</h1>
  <p dir="rtl">هوش مصنوعی: یک رویکرد مدرن — ویرایش چهارم</p>
</div>
<div class="toc-list">{''.join(rows)}</div>
</body>
</html>"""

    HTML(string=html, base_url=str(ROOT)).write_pdf(str(output))
    pages = len(PdfReader(str(output)).pages)
    if pages <= 0:
        raise RuntimeError("TOC PDF is empty")

    page_width, page_height = A4
    margin_left = 17 * 72 / 25.4
    margin_top = 15 * 72 / 25.4
    header_height = 58.0
    row_h = 21.0
    first_row_top = page_height - margin_top - header_height

    rectangles = []
    for index, _entry in enumerate(entries):
        top = first_row_top - index * row_h
        bottom = top - row_h
        rectangles.append((0, margin_left, bottom, page_width - margin_left, top))

    return pages, rectangles


def escape_html(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def add_global_page_numbers(writer: PdfWriter) -> None:
    for index, page in enumerate(writer.pages, 1):
        packet = io.BytesIO()
        c = canvas.Canvas(packet, pagesize=A4)
        c.setFont("Helvetica", 8.5)
        c.drawCentredString(A4[0] / 2, 18, str(index))
        c.save()
        packet.seek(0)
        page.merge_page(PdfReader(packet).pages[0])


def add_internal_link(page, rect, target_page):
    x1, y1, x2, y2 = rect
    annotation = DictionaryObject({
        NameObject("/Type"): NameObject("/Annot"),
        NameObject("/Subtype"): NameObject("/Link"),
        NameObject("/Rect"): ArrayObject([
            FloatObject(x1), FloatObject(y1), FloatObject(x2), FloatObject(y2)
        ]),
        NameObject("/Border"): ArrayObject([
            NumberObject(0), NumberObject(0), NumberObject(0)
        ]),
        NameObject("/Dest"): ArrayObject([
            target_page.indirect_reference, NameObject("/Fit")
        ]),
    })
    annots = page.get("/Annots")
    if annots is None:
        annots = ArrayObject()
        page[NameObject("/Annots")] = annots
    annots.append(annotation)


def _outline_title(item) -> str:
    """Return an outline item's title without depending on a pypdf version."""
    title = getattr(item, "title", None)
    if title is None and isinstance(item, dict):
        title = item.get("/Title")
    return str(title or "").strip()


def _copy_outline_items(
    writer: PdfWriter,
    reader: PdfReader,
    items,
    page_offset: int,
    parent=None,
    skip_first_root: bool = False,
) -> int:
    """Copy a pypdf outline tree into the merged writer.

    WeasyPrint creates the detailed heading outline in each chapter PDF. Once
    chapter PDFs are merged, those destinations still point at the source
    reader's page tree, so they cannot simply be reused. This function resolves
    every destination to its source page number and recreates it against the
    final writer with the chapter page offset applied.

    Nested lists returned by PdfReader.outline represent child bookmarks.
    """
    copied = 0
    index = 0
    while index < len(items):
        item = items[index]
        if isinstance(item, list):
            index += 1
            continue

        title = _outline_title(item)
        try:
            source_page = reader.get_destination_page_number(item)
        except Exception:
            source_page = None

        children = items[index + 1] if index + 1 < len(items) and isinstance(items[index + 1], list) else None

        if skip_first_root and copied == 0:
            # The chapter-level bookmark is already created by build(). Keep
            # its children, but avoid creating a duplicate chapter bookmark.
            if children:
                copied += _copy_outline_items(
                    writer, reader, children, page_offset, parent=parent
                )
            index += 2 if children is not None else 1
            continue

        new_parent = parent
        if source_page is not None and title:
            final_page = page_offset + source_page
            new_parent = writer.add_outline_item(title, final_page, parent=parent)
            copied += 1

        if children:
            copied += _copy_outline_items(
                writer, reader, children, page_offset, parent=new_parent
            )
            index += 2
        else:
            index += 1

    return copied


def add_chapter_outlines(
    writer: PdfWriter,
    rendered,
    chapter_indices: dict[int, int],
) -> int:
    """Create chapter bookmarks and preserve all detailed chapter headings."""
    total = 0
    for number, title, chapter_pdf, _pages in rendered:
        chapter_reader = PdfReader(str(chapter_pdf))
        chapter_root = writer.add_outline_item(
            f"{number:02d}. {title}", chapter_indices[number]
        )
        outline = chapter_reader.outline
        if not outline:
            continue

        # Usually the first root item is the chapter <h1>/<h2> itself. It is
        # redundant because chapter_root above already represents that level.
        # Its children are nevertheless copied under the chapter root.
        copied = _copy_outline_items(
            writer,
            chapter_reader,
            outline,
            page_offset=chapter_indices[number],
            parent=chapter_root,
            skip_first_root=True,
        )
        total += copied

    return total


def build(output: Path, keep_chapters: bool = False) -> None:
    chapters = discover_chapters()
    PDF_DIR.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="aima-pdf-") as temp_name:
        temp_dir = Path(temp_name)
        rendered = render_chapters(chapters, temp_dir)
        toc_path = temp_dir / "toc.pdf"
        font_path = find_font()

        toc_pages = 1
        for _ in range(5):
            cursor = toc_pages + 1
            entries = []
            for number, title, _pdf, pages in rendered:
                entries.append((number, title, cursor))
                cursor += pages
            new_pages, _ = make_toc_pdf(entries, toc_path, font_path)
            if new_pages == toc_pages:
                break
            toc_pages = new_pages
        else:
            raise RuntimeError("TOC page count did not stabilize")

        cursor = toc_pages + 1
        entries = []
        for number, title, _pdf, pages in rendered:
            entries.append((number, title, cursor))
            cursor += pages
        final_toc_pages, toc_rects = make_toc_pdf(entries, toc_path, font_path)

        if final_toc_pages != toc_pages:
            toc_pages = final_toc_pages
            cursor = toc_pages + 1
            entries = []
            for number, title, _pdf, pages in rendered:
                entries.append((number, title, cursor))
                cursor += pages
            final_toc_pages, toc_rects = make_toc_pdf(entries, toc_path, font_path)
            if final_toc_pages != toc_pages:
                raise RuntimeError("TOC page count did not stabilize during final generation")

        writer = PdfWriter()
        for page in PdfReader(str(toc_path)).pages:
            writer.add_page(page)

        chapter_indices = {}
        current_index = toc_pages
        for number, _title, chapter_pdf, _pages in rendered:
            chapter_indices[number] = current_index
            for page in PdfReader(str(chapter_pdf)).pages:
                writer.add_page(page)
                current_index += 1

        heading_count = add_chapter_outlines(writer, rendered, chapter_indices)
        writer.add_outline_item("فهرست مطالب", 0)

        for row_index, (number, _title, _page_number) in enumerate(entries):
            if row_index >= len(toc_rects):
                break
            toc_page_no, x1, y1, x2, y2 = toc_rects[row_index]
            if toc_page_no >= toc_pages:
                continue
            add_internal_link(
                writer.pages[toc_page_no],
                (x1, y1, x2, y2),
                writer.pages[chapter_indices[number]],
            )

        writer.add_metadata({
            "/Title": "هوش مصنوعی: رویکردی نوین — ویرایش چهارم",
            "/Author": "علی رستمی",
            "/Subject": "ترجمهٔ فارسی کتاب Artificial Intelligence: A Modern Approach, 4th Edition",
            "/Creator": "build_pdf.py",
        })

        add_global_page_numbers(writer)

        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("wb") as fh:
            writer.write(fh)

        if keep_chapters:
            chapter_dir = PDF_DIR / "chapters"
            chapter_dir.mkdir(parents=True, exist_ok=True)
            for number, _title, chapter_pdf, _pages in rendered:
                shutil.copy2(chapter_pdf, chapter_dir / f"{number:02d}.pdf")

        final_reader = PdfReader(str(output))
        print("\nPDF successfully created")
        print(f"Output : {output}")
        print(f"Pages  : {len(final_reader.pages)}")
        print(f"Size   : {output.stat().st_size / (1024 * 1024):.2f} MB")
        print(f"TOC    : clickable + page numbers")
        print(f"Outline: chapter bookmarks + {heading_count} detailed heading bookmarks")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "-o", "--output", type=Path, default=DEFAULT_OUTPUT,
        help=f"Output PDF path (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--keep-chapters", action="store_true",
        help="Also copy rendered chapter PDFs to pdf/chapters/",
    )
    args = parser.parse_args()
    build(args.output, args.keep_chapters)


if __name__ == "__main__":
    main()
