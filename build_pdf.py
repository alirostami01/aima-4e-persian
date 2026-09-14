#!/usr/bin/env python3

from __future__ import annotations

import argparse
import re
import sys
import tempfile
from pathlib import Path

from bs4 import BeautifulSoup
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase.pdfmetrics import stringWidth


# ============================================================
# Project paths
# ============================================================

ROOT = Path(__file__).resolve().parent

HTML_DIR = ROOT / "html"
PDF_DIR = ROOT / "pdf"

DEFAULT_OUTPUT = PDF_DIR / "aima-4e-persian.pdf"


# ============================================================
# Book metadata
# ============================================================

BOOK_TITLE = "هوش مصنوعی: رویکردی نوین"
BOOK_TITLE_EN = "Artificial Intelligence: A Modern Approach"
BOOK_AUTHORS = "استوارت راسل و پیتر نورویگ"
BOOK_EDITION = "ویرایش چهارم"
TRANSLATOR = "ترجمهٔ فارسی — علی رستمی"


# ============================================================
# Chapter filename
# ============================================================

CHAPTER_RE = re.compile(
    r"^(?P<number>\d+)-(?P<title>.+)\.html$",
    re.UNICODE,
)


# ============================================================
# Print CSS
# ============================================================

PRINT_CSS = r"""
/*
 * ==========================================================
 * AIMA Persian - PDF print overrides
 * ==========================================================
 */

/*
 * Page setup
 */
@page {
    size: A4;

    margin-top: 18mm;
    margin-bottom: 20mm;
    margin-left: 18mm;
    margin-right: 18mm;

    @bottom-center {
        content: counter(page);
        font-family: "DejaVu Sans", sans-serif;
        font-size: 9pt;
        color: #5b6573;
    }
}

/*
 * Do not print website navigation / branding.
 */
.kicker,
nav.toc,
.footer-nav,
.top-link,
.web-only,
.screen-only,
.print-hidden {
    display: none !important;
}

/*
 * Links should look like normal book text.
 */
a {
    color: inherit !important;
    text-decoration: none !important;
}

/*
 * Avoid printing website-only file links.
 */
a[href^="file://"] {
    display: none !important;
}

/*
 * Keep the original visual design.
 */
body {
    print-color-adjust: exact !important;
    -webkit-print-color-adjust: exact !important;
}

/*
 * The original HTML uses a .page wrapper.
 * Keep its typography/layout, but remove excessive
 * web-page bottom spacing.
 */
.page {
    padding-bottom: 0 !important;
}

/*
 * Chapter title generated specifically for PDF.
 */
.pdf-chapter-title {
    display: block !important;

    margin: 0 0 10mm 0;
    padding: 0 0 5mm 0;

    border-bottom: 2px solid #e4d8c4;

    color: #24344d;

    font-size: 25pt;
    line-height: 1.45;

    page-break-after: avoid;
}

/*
 * The subtitle in the HTML is useful in the book.
 */
.subtitle {
    page-break-after: avoid;
}

/*
 * Headings should stay with the following content.
 */
h1,
h2,
h3,
h4 {
    page-break-after: avoid;
    break-after: avoid;
}

/*
 * Do not split important boxes.
 */
.box,
.tip,
.warn,
.ok,
.formula,
.note,
.quote,
.ex,
.summary-box,
.support-project {
    break-inside: avoid;
    page-break-inside: avoid;
}

/*
 * Keep code blocks together where possible.
 */
pre,
pre.code {
    break-inside: avoid;
    page-break-inside: avoid;

    overflow: visible !important;
    white-space: pre-wrap !important;
}

/*
 * Figures.
 */
figure,
figure.fig {
    break-inside: avoid;
    page-break-inside: avoid;
}

/*
 * Tables.
 */
table {
    width: 100%;
    break-inside: auto;
}

thead {
    display: table-header-group;
}

tr {
    break-inside: avoid;
    page-break-inside: avoid;
}

/*
 * Paragraph typography.
 */
p {
    orphans: 3;
    widows: 3;
}

/*
 * Do not create a blank page at the beginning
 * of every chapter PDF.
 */
.pdf-chapter-title:first-child {
    margin-top: 0;
}
"""


# ============================================================
# Chapter discovery
# ============================================================

def discover_chapters() -> list[tuple[int, Path]]:
    """
    Find all numbered HTML chapters.

    Expected:
        00-پیشگفتار.html
        01-فصل۱-مقدمه.html
        ...
        28-فصل۲۸-آینده-هوش-مصنوعی.html
    """

    if not HTML_DIR.is_dir():
        raise RuntimeError(
            f"HTML directory does not exist:\n{HTML_DIR}"
        )

    chapters = []

    for path in HTML_DIR.iterdir():

        if not path.is_file():
            continue

        match = CHAPTER_RE.match(path.name)

        if not match:
            continue

        number = int(match.group("number"))

        chapters.append((number, path))

    chapters.sort(key=lambda item: item[0])

    return chapters


# ============================================================
# Validate chapters
# ============================================================

def validate_chapters(
    chapters: list[tuple[int, Path]]
) -> None:

    numbers = [number for number, _ in chapters]

    expected = list(range(29))

    if numbers != expected:

        missing = sorted(
            set(expected) - set(numbers)
        )

        extra = sorted(
            set(numbers) - set(expected)
        )

        message = [
            "Chapter validation failed.",
            "",
            f"Found chapters: {numbers}",
        ]

        if missing:
            message.append(
                f"Missing chapters: {missing}"
            )

        if extra:
            message.append(
                f"Unexpected chapters: {extra}"
            )

        raise RuntimeError(
            "\n".join(message)
        )


# ============================================================
# Read chapter title
# ============================================================

def chapter_title(
    html_path: Path
) -> str:

    text = html_path.read_text(
        encoding="utf-8"
    )

    soup = BeautifulSoup(
        text,
        "html.parser",
    )

    # First preference: subtitle.
    subtitle = soup.select_one(
        ".subtitle"
    )

    if subtitle:
        value = subtitle.get_text(
            " ",
            strip=True,
        )

        if value:
            return value

    # Second preference: document title.
    if soup.title:

        value = soup.title.get_text(
            " ",
            strip=True,
        )

        if value:
            return value

    return html_path.stem


# ============================================================
# Clean web-only elements
# ============================================================

def clean_html(
    html_path: Path,
) -> str:
    """
    Modify a COPY of the HTML.

    Original repository HTML is never changed.

    We intentionally keep:
        - original CSS
        - original body
        - figures
        - tables
        - pseudocode
        - colored boxes
        - support section
        - all book content

    We remove:
        - website header/kicker
        - chapter web TOC
        - previous/next navigation
        - back-to-top link
        - generated website footer text
    """

    source = html_path.read_text(
        encoding="utf-8"
    )

    soup = BeautifulSoup(
        source,
        "html.parser",
    )

    # --------------------------------------------------------
    # Remove website navigation.
    # --------------------------------------------------------

    selectors = [
        ".kicker",
        "nav.toc",
        ".footer-nav",
        ".top-link",
        ".web-only",
        ".screen-only",
        ".print-hidden",
    ]

    for selector in selectors:

        for element in soup.select(selector):
            element.decompose()

    # --------------------------------------------------------
    # Remove exact website-generated footer text.
    # --------------------------------------------------------

    generated_text = (
        "این صفحه از ترجمهٔ فارسی فصل‌های کتاب"
    )

    for element in soup.find_all(
        ["p", "div", "section", "footer"]
    ):

        text = element.get_text(
            " ",
            strip=True,
        )

        if (
            generated_text in text
            and "راسل" in text
            and "نورویگ" in text
        ):
            element.decompose()

    # --------------------------------------------------------
    # Remove file:/// links.
    #
    # Keep their visible text so the PDF doesn't lose
    # meaningful content.
    # --------------------------------------------------------

    for link in soup.find_all("a"):

        href = link.get(
            "href",
            "",
        )

        if href.startswith(
            "file://"
        ):

            text = link.get_text(
                " ",
                strip=True,
            )

            if text:
                link.replace_with(
                    soup.new_string(text)
                )
            else:
                link.decompose()

    # --------------------------------------------------------
    # Remove JavaScript.
    # --------------------------------------------------------

    for script in soup.find_all(
        "script"
    ):
        script.decompose()

    # --------------------------------------------------------
    # Create a clean PDF chapter title.
    #
    # The original kicker contains:
    #
    #   📘 AIMA
    #   ترجمه...
    #   فصل X
    #
    # We don't want that website branding in the PDF.
    #
    # Instead, create a clean book-style title.
    # --------------------------------------------------------

    title = chapter_title(
        html_path
    )

    title_element = soup.new_tag(
        "div",
        attrs={
            "class": "pdf-chapter-title"
        },
    )

    title_element.string = title

    body = soup.body

    if body is None:
        raise RuntimeError(
            f"No <body> found in {html_path}"
        )

    # Insert before the existing page content.
    page = body.find(
        class_="page"
    )

    if page is not None:

        page.insert(
            0,
            title_element
        )

    else:

        body.insert(
            0,
            title_element
        )

    # --------------------------------------------------------
    # Add PDF print CSS at the END of <head>.
    #
    # This means the original CSS remains the source of
    # the design and our rules only override print-specific
    # behavior.
    # --------------------------------------------------------

    head = soup.head

    if head is None:
        raise RuntimeError(
            f"No <head> found in {html_path}"
        )

    style = soup.new_tag(
        "style",
        attrs={
            "type": "text/css"
        },
    )

    style.string = PRINT_CSS

    head.append(style)

    return str(soup)


# ============================================================
# Render one chapter
# ============================================================

def render_chapter(
    html_path: Path,
    output_pdf: Path,
) -> None:

    try:
        from weasyprint import HTML
    except ImportError as exc:

        raise RuntimeError(
            "WeasyPrint is not installed.\n\n"
            "Install it with:\n"
            "    pip install weasyprint"
        ) from exc

    cleaned_html = clean_html(
        html_path
    )

    HTML(
        string=cleaned_html,
        base_url=str(
            html_path.parent
        ),
    ).write_pdf(
        str(output_pdf)
    )


# ============================================================
# Merge PDFs
# ============================================================

def merge_pdfs(
    chapter_pdfs: list[
        tuple[int, Path, str]
    ],
    output_pdf: Path,
) -> list[int]:

    writer = PdfWriter()

    chapter_start_pages: list[int] = []

    for number, pdf_path, title in chapter_pdfs:

        reader = PdfReader(
            str(pdf_path)
        )

        start_page = len(
            writer.pages
        )

        chapter_start_pages.append(
            start_page
        )

        for page in reader.pages:
            writer.add_page(page)

    # --------------------------------------------------------
    # PDF metadata
    # --------------------------------------------------------

    writer.add_metadata(
        {
            "/Title": BOOK_TITLE,
            "/Author": BOOK_AUTHORS,
            "/Subject": (
                f"{BOOK_TITLE} — {BOOK_EDITION}"
            ),
            "/Creator": (
                "aima-4e-persian build_pdf.py"
            ),
            "/Producer": (
                "WeasyPrint + pypdf"
            ),
        }
    )

    # --------------------------------------------------------
    # Bookmarks / outline
    # --------------------------------------------------------

    for (
        (number, _pdf_path, title),
        page_number,
    ) in zip(
        chapter_pdfs,
        chapter_start_pages,
    ):

        writer.add_outline_item(
            title,
            page_number,
        )

    output_pdf.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with output_pdf.open(
        "wb"
    ) as file:

        writer.write(file)

    return chapter_start_pages


# ============================================================
# Page numbering
# ============================================================

def add_page_numbers(
    input_pdf: Path,
    output_pdf: Path,
) -> None:
    """
    Add global page numbers after all chapter PDFs
    have been merged.

    This guarantees that numbering does not restart
    at every chapter.
    """

    reader = PdfReader(
        str(input_pdf)
    )

    writer = PdfWriter()

    total_pages = len(
        reader.pages
    )

    for index, page in enumerate(
        reader.pages,
        start=1,
    ):

        # ----------------------------------------------------
        # Create a one-page transparent-ish overlay.
        # ----------------------------------------------------

        with tempfile.NamedTemporaryFile(
            suffix=".pdf"
        ) as temp:

            temp_path = Path(
                temp.name
            )

            c = canvas.Canvas(
                str(temp_path),
                pagesize=A4,
            )

            width, height = A4

            number_text = str(index)

            c.setFont(
                "Helvetica",
                9,
            )

            text_width = stringWidth(
                number_text,
                "Helvetica",
                9,
            )

            # Bottom center.
            x = (
                width / 2
                - text_width / 2
            )

            y = 12 * 2.83465

            c.drawString(
                x,
                y,
                number_text,
            )

            c.save()

            overlay_reader = PdfReader(
                str(temp_path)
            )

            page.merge_page(
                overlay_reader.pages[0]
            )

        writer.add_page(page)

    writer.add_metadata(
        {
            "/Title": BOOK_TITLE,
            "/Author": BOOK_AUTHORS,
            "/Subject": (
                f"{BOOK_TITLE} — {BOOK_EDITION}"
            ),
            "/Creator": (
                "aima-4e-persian build_pdf.py"
            ),
        }
    )

    with output_pdf.open(
        "wb"
    ) as file:

        writer.write(file)


# ============================================================
# Main build
# ============================================================

def build(
    output_pdf: Path,
    keep_chapters: bool = False,
) -> None:

    print()
    print("=" * 70)
    print("AIMA Persian — PDF Builder")
    print("=" * 70)
    print()

    chapters = discover_chapters()

    print(
        f"Detected {len(chapters)} HTML files."
    )

    validate_chapters(
        chapters
    )

    print(
        "✓ Chapters 00–28 detected."
    )

    print()

    # --------------------------------------------------------
    # Temporary working directory.
    # --------------------------------------------------------

    with tempfile.TemporaryDirectory(
        prefix="aima-pdf-"
    ) as temp:

        temp_dir = Path(temp)

        chapter_pdfs = []

        # ----------------------------------------------------
        # Render each chapter DIRECTLY from its own HTML.
        # ----------------------------------------------------

        for number, html_path in chapters:

            title = chapter_title(
                html_path
            )

            chapter_pdf = (
                temp_dir
                / f"chapter-{number:02d}.pdf"
            )

            print(
                f"[{number:02d}/28] "
                f"{html_path.name}"
            )

            render_chapter(
                html_path,
                chapter_pdf,
            )

            # ------------------------------------------------
            # Verify that WeasyPrint actually produced pages.
            # ------------------------------------------------

            reader = PdfReader(
                str(chapter_pdf)
            )

            page_count = len(
                reader.pages
            )

            if page_count == 0:
                raise RuntimeError(
                    f"Chapter {number:02d} "
                    f"produced ZERO pages:\n"
                    f"{html_path}"
                )

            print(
                f"       → {page_count} pages"
            )

            chapter_pdfs.append(
                (
                    number,
                    chapter_pdf,
                    title,
                )
            )

        print()

        # ----------------------------------------------------
        # First merge.
        # ----------------------------------------------------

        merged_pdf = (
            temp_dir
            / "merged.pdf"
        )

        print(
            "Merging chapter PDFs..."
        )

        merge_pdfs(
            chapter_pdfs,
            merged_pdf,
        )

        # ----------------------------------------------------
        # Add global page numbers.
        # ----------------------------------------------------

        output_pdf.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        numbered_pdf = (
            temp_dir
            / "numbered.pdf"
        )

        print(
            "Adding global page numbers..."
        )

        add_page_numbers(
            merged_pdf,
            numbered_pdf,
        )

        # ----------------------------------------------------
        # Final output.
        # ----------------------------------------------------

        output_pdf.write_bytes(
            numbered_pdf.read_bytes()
        )

        # ----------------------------------------------------
        # Optionally keep individual chapter PDFs.
        # ----------------------------------------------------

        if keep_chapters:

            chapters_dir = (
                output_pdf.parent
                / "chapters"
            )

            chapters_dir.mkdir(
                parents=True,
                exist_ok=True,
            )

            for (
                number,
                chapter_pdf,
                _title,
            ) in chapter_pdfs:

                destination = (
                    chapters_dir
                    / f"{number:02d}.pdf"
                )

                destination.write_bytes(
                    chapter_pdf.read_bytes()
                )

            print()
            print(
                f"Chapter PDFs saved to:\n"
                f"  {chapters_dir}"
            )

    # --------------------------------------------------------
    # Final validation.
    # --------------------------------------------------------

    final_reader = PdfReader(
        str(output_pdf)
    )

    total_pages = len(
        final_reader.pages
    )

    size_mb = (
        output_pdf.stat().st_size
        / 1024 / 1024
    )

    print()
    print("=" * 70)
    print("PDF successfully created")
    print("=" * 70)
    print()
    print(
        f"Output : {output_pdf}"
    )
    print(
        f"Pages  : {total_pages}"
    )
    print(
        f"Size   : {size_mb:.2f} MB"
    )
    print()


# ============================================================
# CLI
# ============================================================

def parse_args():

    parser = argparse.ArgumentParser(
        description=(
            "Build the AIMA Persian book PDF "
            "directly from the repository HTML files."
        )
    )

    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=(
            "Output PDF path "
            f"(default: {DEFAULT_OUTPUT})"
        ),
    )

    parser.add_argument(
        "--keep-chapters",
        action="store_true",
        help=(
            "Also save individual chapter PDFs "
            "under pdf/chapters/"
        ),
    )

    return parser.parse_args()


# ============================================================
# Entry point
# ============================================================

def main() -> int:

    args = parse_args()

    try:

        build(
            output_pdf=args.output.resolve(),
            keep_chapters=args.keep_chapters,
        )

        return 0

    except KeyboardInterrupt:

        print(
            "\nBuild cancelled."
        )

        return 130

    except Exception as exc:

        print()
        print(
            "ERROR:",
            exc,
            file=sys.stderr,
        )
        print()

        return 1


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
