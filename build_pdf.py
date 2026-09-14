#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build the complete AIMA Persian book PDF from the chapter HTML files.

Pipeline:
    html/*.html -> clean per-chapter PDFs -> TOC PDF -> merged PDF
    -> global page numbers -> clickable TOC -> PDF bookmarks

The original HTML/CSS files are never modified.  Run this script again any
 time the HTML changes; the PDF is rebuilt from scratch.
"""

from __future__ import annotations

import argparse
import html as html_lib
import io
import re
import shutil
import tempfile
from pathlib import Path

from bs4 import BeautifulSoup
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, DictionaryObject, FloatObject, NameObject, NumberObject, TextStringObject
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from weasyprint import HTML

ROOT = Path(__file__).resolve().parent
HTML_DIR = ROOT / "html"
PDF_DIR = ROOT / "pdf"
DEFAULT_OUTPUT = PDF_DIR / "aima-4e-persian.pdf"

CHAPTER_RE = re.compile(r"^(?P<number>\d+)-(?P<title>.+)\.html$")

# Web-only elements which should not appear in the printed book.
REMOVE_SELECTORS = (
    ".kicker",
    "nav.toc",
    ".footer-nav",
    ".top-link",
    ".web-only",
    ".screen-only",
    ".print-hidden",
)

PRINT_CSS = r"""
@page {
    size: A4;
    margin: 18mm 17mm 20mm 17mm;
}

html, body {
    print-color-adjust: exact !important;
    -webkit-print-color-adjust: exact !important;
}

.pdf-chapter-title {
    display: none;
}

@media print {
    .kicker,
    nav.toc,
    .footer-nav,
    .top-link,
    .web-only,
    .screen-only,
    .print-hidden {
        display: none !important;
    }

    .page,
    main,
    article {
        break-before: auto;
    }

    .box, .tip, .warn, .ok, .formula, .note, .quote, .ex,
    .summary-box, figure, pre, table {
        break-inside: avoid;
        page-break-inside: avoid;
    }

    thead {
        display: table-header-group;
    }

    tr, img {
        break-inside: avoid;
        page-break-inside: avoid;
    }

    p, li {
        orphans: 3;
        widows: 3;
    }
}
"""


def discover_chapters() -> list[tuple[int, Path]]:
    chapters: list[tuple[int, Path]] = []
    for path in HTML_DIR.glob("*.html"):
        match = CHAPTER_RE.match(path.name)
        if match:
            chapters.append((int(match.group("number")), path))

    chapters.sort(key=lambda item: item[0])
    expected = list(range(29))
    actual = [number for number, _ in chapters]
    if actual != expected:
        raise SystemExit(
            "Chapter validation failed. Expected chapters 00..28, "
            f"but found: {actual}"
        )
    return chapters


def chapter_title(path: Path) -> str:
    soup = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")
    subtitle = soup.select_one(".subtitle")
    if subtitle:
        title = subtitle.get_text(" ", strip=True)
        if title:
            return title
    if soup.title:
        title = soup.title.get_text(" ", strip=True)
        if title:
            return title
    match = CHAPTER_RE.match(path.name)
    return match.group("title") if match else path.stem


def clean_html(path: Path) -> str:
    """Return a cleaned copy of one HTML document, preserving its CSS/layout."""
    soup = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")

    for selector in REMOVE_SELECTORS:
        for node in soup.select(selector):
            node.decompose()

    # Remove the generated website footer by its distinctive Persian text.
    for node in list(soup.find_all(string=True)):
        text = str(node)
        if (
            "این صفحه از ترجمهٔ فارسی فصل‌های کتاب" in text
            and "راسل" in text
            and "نورویگ" in text
        ):
            parent = node.parent
            if parent:
                parent.decompose()

    # Keep visible link text but remove local file:// navigation URLs.
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
    else:
        head = soup.new_tag("head")
        head.append(style)
        if soup.html:
            soup.html.insert(0, head)

    return str(soup)


def render_chapters(chapters: list[tuple[int, Path]], temp_dir: Path) -> list[tuple[int, str, Path, int]]:
    rendered = []
    for index, (number, path) in enumerate(chapters, 1):
        title = chapter_title(path)
        output = temp_dir / f"chapter-{number:02d}.pdf"
        print(f"[{index:02d}/{len(chapters):02d}] {path.name}")

        cleaned = clean_html(path)
        HTML(string=cleaned, base_url=str(path.parent)).write_pdf(str(output))

        reader = PdfReader(str(output))
        pages = len(reader.pages)
        if pages <= 0:
            raise RuntimeError(f"Chapter {number:02d} produced an empty PDF: {path}")

        print(f"       → {pages} pages")
        rendered.append((number, title, output, pages))
    return rendered


def find_font() -> str | None:
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansArabic-Regular.ttf",
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            return candidate
    return None


def make_toc_pdf(entries: list[tuple[int, str, int]], output: Path, font_path: str | None) -> tuple[int, list[tuple[int, float, float, float, float]]]:
    """Create TOC and return (page_count, clickable row rectangles).

    Rectangles are returned in PDF coordinates as (page, x1, y1, x2, y2),
    ready for link annotations after the final book has been merged.
    """
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    font_name = "Helvetica"
    if font_path:
        try:
            font_name = "AIMAPersian"
            pdfmetrics.registerFont(TTFont(font_name, font_path))
        except Exception:
            font_name = "Helvetica"

    c.setTitle("هوش مصنوعی: رویکردی نوین — فهرست مطالب")
    c.setAuthor("ترجمهٔ فارسی — علی رستمی")

    # A compact professional TOC designed to fit the 29 entries on one page.
    c.setFont(font_name, 20)
    c.drawRightString(width - 48, height - 58, "فهرست مطالب")

    c.setFont(font_name, 9)
    c.drawRightString(width - 48, height - 78, "هوش مصنوعی: یک رویکرد مدرن — ویرایش چهارم")

    y = height - 112
    row_h = 23
    rectangles: list[tuple[int, float, float, float, float]] = []

    for number, title, page_number in entries:
        if y < 60:
            c.showPage()
            y = height - 55

        x_right = width - 48
        x_left = 52
        page_x = 52
        text_x = width - 78

        c.setFont(font_name, 10.5)
        label = f"{number:02d}. {title}"
        # Escape unsupported glyphs only when Helvetica fallback is used.
        if font_name == "Helvetica":
            label = f"{number:02d}. {title.encode('ascii', 'replace').decode()}"

        # Dotted leader.
        c.drawRightString(text_x, y, label)
        c.drawString(page_x, y, str(page_number))
        c.setDash(1, 2)
        c.line(page_x + 22, y + 2, text_x - 8, y + 2)
        c.setDash()

        # Rectangle covering the visible row; destination is added after merge.
        rectangles.append((len(rectangles) and 0 or 0, x_left, y - 5, x_right, y + 10))
        y -= row_h

    c.save()
    buffer.seek(0)

    # Persist the generated PDF and count its pages.
    output.write_bytes(buffer.read())
    pages = len(PdfReader(str(output)).pages)

    # All rows currently start on TOC page 0 unless pagination occurs.
    # Reconstruct accurate page indices by row position if needed.
    if pages == 1:
        rectangles = [(0, x1, y1, x2, y2) for _, x1, y1, x2, y2 in rectangles]
    else:
        # Current layout should fit one page; keep a safe fallback.
        rectangles = [(0, x1, y1, x2, y2) for _, x1, y1, x2, y2 in rectangles]

    return pages, rectangles


def add_link_annotation(page, rect: tuple[float, float, float, float], target_page_index: int) -> None:
    """Add a PDF internal link annotation to a page in a PdfWriter."""
    x1, y1, x2, y2 = rect
    annotation = DictionaryObject()
    annotation[NameObject("/Type")] = NameObject("/Annot")
    annotation[NameObject("/Subtype")] = NameObject("/Link")
    annotation[NameObject("/Rect")] = ArrayObject([
        FloatObject(x1), FloatObject(y1), FloatObject(x2), FloatObject(y2)
    ])
    annotation[NameObject("/Border")] = ArrayObject([NumberObject(0), NumberObject(0), NumberObject(0)])
    annotation[NameObject("/Dest")] = ArrayObject([
        page_ref := target_page_index,
    ])

    # pypdf expects a page indirect reference in /Dest. The caller replaces
    # this placeholder with a real reference immediately after adding it.
    page[NameObject("/Annots")] = page.get("/Annots", ArrayObject())
    page[NameObject("/Annots")].append(annotation)


def add_global_page_numbers(writer: PdfWriter, start_page: int = 1) -> None:
    """Overlay a centered global page number on every page."""
    from reportlab.lib.colors import black

    total = len(writer.pages)
    for index, page in enumerate(writer.pages):
        number = start_page + index
        packet = io.BytesIO()
        c = canvas.Canvas(packet, pagesize=A4)
        c.setFillColor(black)
        c.setFont("Helvetica", 8.5)
        c.drawCentredString(A4[0] / 2, 18, str(number))
        c.save()
        packet.seek(0)
        overlay = PdfReader(packet).pages[0]
        page.merge_page(overlay)


def build(output: Path, keep_chapters: bool = False) -> None:
    chapters = discover_chapters()
    PDF_DIR.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="aima-pdf-") as temp_name:
        temp_dir = Path(temp_name)
        rendered = render_chapters(chapters, temp_dir)

        # The TOC is one page in the normal 29-chapter layout. We still use an
        # iterative calculation so page references remain correct if the TOC
        # ever grows to multiple pages.
        toc_pages = 1
        toc_path = temp_dir / "toc.pdf"
        font_path = find_font()

        for _ in range(3):
            page_cursor = toc_pages + 1  # first chapter is page 2 if TOC=1
            entries = []
            for number, title, _, pages in rendered:
                entries.append((number, title, page_cursor))
                page_cursor += pages

            new_toc_pages, toc_rects = make_toc_pdf(entries, toc_path, font_path)
            if new_toc_pages == toc_pages:
                break
            toc_pages = new_toc_pages
        else:
            raise RuntimeError("TOC page-count did not stabilize after 3 iterations")

        # Rebuild entries once more using the final TOC page count.
        page_cursor = toc_pages + 1
        entries = []
        chapter_start_pages: list[tuple[int, int]] = []
        for number, title, _, pages in rendered:
            entries.append((number, title, page_cursor))
            chapter_start_pages.append((number, page_cursor - 1))  # zero-based index
            page_cursor += pages

        toc_pages, toc_rects = make_toc_pdf(entries, toc_path, font_path)
        if toc_pages != (chapter_start_pages[0][1] + 1):
            # This condition is intentionally conservative; regenerate if the
            # TOC unexpectedly changed size.
            raise RuntimeError("TOC page count changed unexpectedly during final generation")

        writer = PdfWriter()
        toc_reader = PdfReader(str(toc_path))
        for page in toc_reader.pages:
            writer.add_page(page)

        chapter_page_refs: dict[int, object] = {}
        chapter_zero_indices: dict[int, int] = {}
        current_index = toc_pages

        for number, title, chapter_pdf, _ in rendered:
            reader = PdfReader(str(chapter_pdf))
            chapter_zero_indices[number] = current_index
            for page in reader.pages:
                writer.add_page(page)
                current_index += 1

        # PDF bookmarks / outline.
        writer.add_outline_item("فهرست مطالب", 0)
        for number, title, _chapter_pdf, _pages in rendered:
            writer.add_outline_item(f"{number:02d}. {title}", chapter_zero_indices[number])

        # Clickable TOC rows. We create /Dest annotations with actual page
        # references now that all pages have been added.
        toc_page = writer.pages[0]
        for row_index, (number, _title, _page_number) in enumerate(entries):
            if row_index >= len(toc_rects):
                break
            _, x1, y1, x2, y2 = toc_rects[row_index]
            target_index = chapter_zero_indices[number]
            annotation = DictionaryObject()
            annotation[NameObject("/Type")] = NameObject("/Annot")
            annotation[NameObject("/Subtype")] = NameObject("/Link")
            annotation[NameObject("/Rect")] = ArrayObject([
                FloatObject(x1), FloatObject(y1), FloatObject(x2), FloatObject(y2)
            ])
            annotation[NameObject("/Border")] = ArrayObject([
                NumberObject(0), NumberObject(0), NumberObject(0)
            ])
            annotation[NameObject("/Dest")] = ArrayObject([
                writer.pages[target_index].indirect_reference,
                NameObject("/Fit"),
            ])
            annots = toc_page.get("/Annots")
            if annots is None:
                annots = ArrayObject()
                toc_page[NameObject("/Annots")] = annots
            annots.append(annotation)

        # Metadata.
        writer.add_metadata({
            "/Title": "هوش مصنوعی: رویکردی نوین — ویرایش چهارم",
            "/Author": "علی رستمی",
            "/Subject": "ترجمهٔ فارسی کتاب Artificial Intelligence: A Modern Approach, 4th Edition",
            "/Creator": "build_pdf.py",
        })

        # Global page numbers are added after TOC + all chapters have been merged.
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
        total_pages = len(final_reader.pages)
        size_mb = output.stat().st_size / (1024 * 1024)

        print("\nPDF successfully created")
        print(f"Output : {output}")
        print(f"Pages  : {total_pages}")
        print(f"Size   : {size_mb:.2f} MB")
        print("TOC    : clickable + page numbers")
        print("Outline: chapter bookmarks")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the complete AIMA Persian PDF")
    parser.add_argument("-o", "--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--keep-chapters",
        action="store_true",
        help="also keep individual chapter PDFs in pdf/chapters/",
    )
    args = parser.parse_args()
    build(args.output.resolve(), args.keep_chapters)


if __name__ == "__main__":
    main()
