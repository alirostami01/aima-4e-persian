#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ساخت PDF کتاب «هوش مصنوعی: رویکردی نوین» (AIMA 4e) از فایل‌های HTML.

خروجی‌ها:
  pdf/aima-4e-persian.pdf       کل کتاب: صفحهٔ عنوان (با درج خودکار نسخه، تاریخ و کامیت)،
                                فهرست مطالب (با شمارهٔ صفحه و پیوند قابل کلیک)،
                                پیشگفتار، فصل‌های ۱ تا ۲۸ + نشانک‌های (Bookmarks) PDF
  pdf/chapters/chapter-NN.pdf   PDF جداگانهٔ هر فصل (با نشانک بخش‌های همان فصل)

موتور تبدیل: Chromium / Google Chrome (از راه Playwright) برای چیدمان بی‌نقص راست‌به‌چپ،
شکل‌دهی حروف فارسی و تفکیک صفحات چاپی، و PyMuPDF برای نشانک‌ها، شمارهٔ صفحه‌های فهرست و فشرده‌سازی.
فونت‌ها از pdf/fonts بارگذاری می‌شوند (Vazirmatn برای متن، DejaVu Sans Mono برای کد)
و به نصب فونت روی سیستم نیازی نیست.

پیش‌نیازها:
    pip install playwright pymupdf
    playwright install chromium  (یا استفاده از Chrome/Chromium نصب‌شده روی سیستم)

اجرا:
    python3 build_pdf.py                      # کل کتاب + همهٔ فصل‌ها
    python3 build_pdf.py --book-only          # فقط کل کتاب
    python3 build_pdf.py --chapters-only      # فقط PDF فصل‌ها
    python3 build_pdf.py --chapters 1 2       # فقط فصل‌های مشخص (0 = پیشگفتار)
    python3 build_pdf.py --page-size A4 --font-size 11
"""

from __future__ import annotations

import argparse
import datetime
import html as htmllib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
HTML_DIR = ROOT / "html"
PDF_DIR = ROOT / "pdf"
FONTS_DIR = PDF_DIR / "fonts"
DEFAULT_OUTPUT = PDF_DIR / "aima-4e-persian.pdf"

FA = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
PLACEHOLDER = "۸۸۸"

TITLE_FA = "هوش مصنوعی: رویکردی نوین"
TITLE_EN = "Artificial Intelligence: A Modern Approach (4th Edition)"
AUTHORS = "استوارت راسل و پیتر نورویگ"
SUBTITLE = "ویرایش چهارم — استوارت راسل و پیتر نورویگ"
NOTE = "ترجمهٔ فارسی بر پایهٔ ویرایش چهارم کتاب مرجع هوش مصنوعی (AIMA 4th Edition)"

PARTS = {
    1: "بخش اول: هوش مصنوعی",
    3: "بخش دوم: حل مسئله",
    7: "بخش سوم: دانش، استدلال و برنامه‌ریزی",
    12: "بخش چهارم: دانش و استدلال با عدم قطعیت",
    19: "بخش پنجم: یادگیری ماشین",
    23: "بخش ششم: ارتباط، ادراک و کنش",
    27: "بخش هفتم: نتیجه‌گیری‌ها",
}

REMOVE_SELECTORS = (
    ".kicker", "nav.toc", ".footer-nav", ".top-link",
    ".web-only", ".screen-only", ".print-hidden",
)


# ───────────────────────────── Jalali & Versioning ─────────────────────────────
def gregorian_to_jalali(gy: int, gm: int, gd: int) -> tuple[int, int, int]:
    """تبدیل تاریخ میلادی به هجری شمسی (الگوریتم بدون وابستگی)."""
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    if gy > 1600:
        jy = 979
        gy -= 1600
    else:
        jy = 0
        gy -= 621
    gy2 = gy if gm > 2 else gy - 1
    days = 365 * gy + (gy2 + 4) // 4 - (gy2 + 100) // 100 + (gy2 + 400) // 400 - 80 + gd + g_d_m[gm - 1]
    jy += 33 * (days // 12053)
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm = 1 + days // 31
        jd = 1 + days % 31
    else:
        jm = 7 + (days - 186) // 30
        jd = 1 + (days - 186) % 30
    return jy, jm, jd


def get_version_info() -> dict:
    """استخراج پویای نسخه، تعداد کامیت‌ها، هش آخرین کامیت و تاریخ ساخت."""
    try:
        commit_hash = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(ROOT), text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:
        commit_hash = "master"

    try:
        commit_count = subprocess.check_output(
            ["git", "rev-list", "--count", "HEAD"],
            cwd=str(ROOT), text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:
        commit_count = "1"

    try:
        status = subprocess.check_output(
            ["git", "status", "--porcelain"],
            cwd=str(ROOT), text=True, stderr=subprocess.DEVNULL
        ).strip()
        dirty_flag = " (با تغییرات محلی)" if status else ""
    except Exception:
        dirty_flag = ""

    now = datetime.datetime.now()
    jy, jm, jd = gregorian_to_jalali(now.year, now.month, now.day)
    jalali_months = [
        "فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
        "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"
    ]
    month_name = jalali_months[jm - 1]

    version_num = f"۱.۰.{str(commit_count).translate(FA)}"
    jalali_str = f"{str(jd).translate(FA)} {month_name} {str(jy).translate(FA)}"
    gregorian_str = now.strftime("%Y/%m/%d").translate(FA)

    return {
        "version_num": version_num,
        "commit_hash": commit_hash,
        "dirty_flag": dirty_flag,
        "jalali_date": jalali_str,
        "gregorian_date": gregorian_str,
    }


# ───────────────────────────── CSS ─────────────────────────────
def css(page_size: str, font_pt: float) -> str:
    f = FONTS_DIR.as_uri()
    return f"""
@font-face {{ font-family: 'VazirPDF'; src: url('{f}/Vazirmatn-Regular.ttf'); font-weight: 400; }}
@font-face {{ font-family: 'VazirPDF'; src: url('{f}/Vazirmatn-Bold.ttf'); font-weight: 700; }}
@font-face {{ font-family: 'MonoPDF'; src: url('{f}/DejaVuSansMono.ttf'); font-weight: 400; }}
@font-face {{ font-family: 'MonoPDF'; src: url('{f}/DejaVuSansMono-Bold.ttf'); font-weight: 700; }}

@page {{
  size: {page_size};
  margin: 20mm 18mm 18mm 18mm;
  @bottom-center {{ content: counter(page, persian); font-family: 'VazirPDF'; font-size: 9pt; color: #666; }}
}}
@page cover {{ @bottom-center {{ content: none; }} }}
@page bookcover {{
  size: {page_size};
  margin: 0;
  @bottom-center {{ content: none; }}
}}

html {{ -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
body {{ margin: 0; font-family: 'VazirPDF', sans-serif; font-size: {font_pt}pt; line-height: 1.9; color: #1a1a1a; }}

/* حذف قیدهای نمایشی صفحه و کادرها برای چاپ تمیز */
article {{
  max-width: none !important; margin: 0 !important; padding: 0 !important;
  border: none !important; border-radius: 0 !important; box-shadow: none !important;
  font-family: 'VazirPDF', sans-serif !important; line-height: 1.9 !important;
}}
article.unit {{ break-before: page; }}
article.unit:first-child {{ break-before: auto; }}
article.unit.single {{ break-before: auto; }}

article h1 {{
  font-size: 21pt !important; color: #2c5f8a !important;
  border-bottom: 2.5pt solid #2c5f8a; padding-bottom: 3mm; margin-top: 0; margin-bottom: 5mm;
}}
article h2 {{
  font-size: 15pt !important; color: #2c5f8a !important;
  border-right: 4pt solid #8b2942; padding-right: 3mm; background: #fbf7f0;
  margin-top: 8mm; margin-bottom: 3mm; padding-top: 1.5mm; padding-bottom: 1.5mm;
}}
article h3 {{ font-size: 13pt !important; color: #1b5c5a !important; margin-top: 6mm; margin-bottom: 2.5mm; }}
article h4 {{ font-size: 11pt !important; color: #24344d !important; margin-top: 5mm; margin-bottom: 2mm; }}

bdi[style*="monospace"], code, pre, pre *, td[style*="monospace"] {{ font-family: 'MonoPDF', monospace !important; }}
bdi[style*="monospace"] {{ font-size: .86em !important; display: inline !important;
  -webkit-box-decoration-break: clone; box-decoration-break: clone; }}
pre, pre.code {{
  white-space: pre-wrap !important; overflow-wrap: anywhere; font-size: 8.5pt !important; line-height: 1.5 !important;
  background: #24344d !important; color: #f0f4f8 !important; padding: 4mm 5mm !important; border-radius: 6px !important;
  margin: 3.5mm 0 !important;
}}
pre code, pre.code code {{ background: transparent !important; border: none !important; color: inherit !important; font-size: inherit !important; }}
code {{ background: #eef2f8; border: 1px solid #d7dee8; border-radius: 4px; padding: 0.5mm 1.5mm; font-size: .88em; }}

h1, h2, h3, h4, h5 {{ break-after: avoid; }}
p, li {{ orphans: 3; widows: 3; text-align: justify; text-justify: inter-word; }}
figure, blockquote, aside, pre, tr, .box, .tip, .warn, .ok, .formula, .note, .quote, .ex, .summary-box {{
  break-inside: avoid;
}}
figure {{ text-align: center; margin: 5mm 0; }}
figure img {{ max-height: 185mm; max-width: 100%; object-fit: contain; }}
figure figcaption {{ font-size: 9pt; color: #555; text-align: justify; margin-top: 2.5mm; line-height: 1.6; }}
figure figcaption strong {{ color: #8b2942; }}

table {{ font-size: .9em !important; width: 100%; border-collapse: collapse; margin: 4mm 0; }}
th, td {{ border: 1px solid #d0d7de; padding: 2mm 3mm; vertical-align: top; }}
th {{ background: #2c5f8a !important; color: #fff !important; font-weight: 700; text-align: right; }}
tr:nth-child(even) td {{ background: #fbf7f0; }}
thead {{ display: table-header-group; }}

a {{ color: inherit; text-decoration: none; }}
hr {{ border: none !important; border-top: .6pt solid #c8c8c8 !important; margin: 6mm 0 !important; }}

/* جعبه‌ها و پیام‌ها */
.box, .tip, .warn, .ok, .formula, .note, .quote {{
  border-radius: 6px; padding: 3mm 4mm; margin: 3.5mm 0; border: 1px solid #e2d8c8; font-size: .95em;
}}
.box {{ background: #fdfdfc; }}
.tip {{ background: #fffcf0; border-color: #ead7a0; }}
.warn {{ background: #fdf2f4; border-color: #e3b7c2; }}
.ok {{ background: #f0f8f4; border-color: #b7dec8; }}
.formula {{ background: #f0f7f7; border-color: #b7d8d6; }}
.note {{ background: #f2f5fa; border-color: #c9d4e4; }}
.quote {{ background: #fff; border-right: 4pt solid #b8923a; color: #3f4653; font-style: italic; }}
.lead {{ font-size: 1.05em; background: #fffcf8; border: 1px solid #e8dec8; border-radius: 6px; padding: 3.5mm 4.5mm; margin-bottom: 4mm; }}

.summary-box {{ background: #24344d; color: #f6f0e6; border-radius: 8px; padding: 4.5mm 5.5mm; margin-top: 5mm; }}
.summary-box h2.sum-head {{ color: #f4e7c4 !important; background: transparent !important; border: none !important; padding: 0 !important; margin-top: 0 !important; }}
.summary-box h3 {{ color: #f0d48a !important; }}
.summary-box p, .summary-box li {{ color: #e9eef7 !important; }}

.footnotes {{ background: #f7f6f2; border: 1px solid #e0dad0; border-radius: 6px; padding: 3mm 4mm; margin-top: 4mm; font-size: .88em; }}
.fn {{ color: #454e5c; margin: 1.5mm 0; }}

/* بخش حمایت از پروژه */
section.support-project {{
  break-after: page; margin-top: 25mm !important; padding: 6mm 8mm !important;
  border: 1px solid #e2d8c8; border-radius: 8px; background: #fdfdfc;
}}
section.support-project h2 {{ border-right: 4pt solid #2c5f8a !important; background: transparent !important; }}

/* روی جلد کتاب */
.book-cover-image {{
  page: bookcover;
  width: 100vw;
  height: 100vh;
  margin: 0 !important;
  padding: 0 !important;
  break-after: page;
  overflow: hidden;
  background: #142b55;
  display: flex;
  align-items: center;
  justify-content: center;
}}
.book-cover-image img {{
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}}

/* صفحهٔ عنوان */
.cover {{
  page: cover; height: 245mm; display: flex; flex-direction: column; justify-content: center;
  text-align: center; break-after: page;
}}
.cover .t {{ font-size: 28pt; font-weight: 700; color: #2c5f8a; line-height: 1.6; }}
.cover .en {{ direction: ltr; font-size: 14pt; font-weight: 700; margin-top: 8mm; color: #333; }}
.cover .sub {{ font-size: 13pt; margin-top: 6mm; color: #444; }}
.cover .note {{ font-size: 10pt; color: #666; margin-top: 15mm; }}
.cover .bar {{ width: 60mm; height: 2mm; background: #2c5f8a; margin: 10mm auto 0; }}

/* برچسب نسخه در صفحه اول */
.cover .version-box {{
  margin: 16mm auto 0;
  display: inline-flex;
  justify-content: center;
}}
.cover .version-box .v-pill {{
  background: #2c5f8a;
  color: #ffffff;
  padding: 2mm 6mm;
  border-radius: 20px;
  font-weight: 700;
  font-size: 9.5pt;
  letter-spacing: 0.3px;
}}

/* فهرست مطالب */
.toc {{ page: cover; break-after: page; }}
.toc .h {{
  font-size: 20pt; font-weight: 700; color: #2c5f8a; border-bottom: 3px solid #2c5f8a;
  padding-bottom: 2mm; margin-bottom: 4mm;
}}
.toc .part {{
  font-weight: 700; color: #2c5f8a; margin: 5mm 0 1.5mm; font-size: 1.05em;
  border-bottom: 1px solid #e2e8f0; padding-bottom: 1mm;
}}
.toc a.row {{ display: flex; align-items: baseline; gap: 2mm; color: inherit; break-inside: avoid; }}
.toc a.row .dots {{
  flex: 1; height: 1pt; min-width: 6mm; transform: translateY(-1.2mm);
  background: radial-gradient(circle, #999 0.5pt, transparent 0.6pt) repeat-x left center / 3pt 1pt;
}}
.toc a.row .pg {{ min-width: 9mm; text-align: left; }}
.toc a.l1 {{ font-weight: 700; margin-top: 2.2mm; font-size: 1em; }}
.toc a.l2 {{ padding-right: 6mm; font-size: .9em; color: #333; margin-top: 1mm; }}
"""


# ───────────────────────────── HTML Assembly ─────────────────────────────
def strip_tags(s: str) -> str:
    return re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", "", s))).strip()


def cover_image_html() -> str:
    img_uri = (ROOT / "figures" / "aima-4e-persian.jpeg").as_uri()
    return (
        f'<div id="front-cover" class="book-cover-image">'
        f'<img src="{img_uri}" alt="روی جلد کتاب">'
        f'</div>'
    )


def cover_html(version_info: dict) -> str:
    v = version_info
    commit_str = f" (کامیت: {v['commit_hash']}{v['dirty_flag']})" if v.get("commit_hash") else ""
    return (
        f'<section id="cover" class="cover">'
        f'<div class="t">{TITLE_FA}</div>'
        f'<div class="bar"></div>'
        f'<div class="en">{TITLE_EN}</div>'
        f'<div class="sub">{SUBTITLE}</div>'
        f'<div class="note">{NOTE}</div>'
        f'<div class="version-box">'
        f'<div class="v-pill">نسخهٔ ترجمهٔ کتاب: {v["version_num"]}{commit_str}</div>'
        f'</div></section>'
    )


def toc_html(entries: list, chapter_of: dict, pages: list[int] | None = None) -> str:
    rows = ['<nav class="toc" aria-label="فهرست مطالب"><div class="h">فهرست مطالب</div>']
    pg_done = []
    for lvl, eid, title_html, *_ in entries:
        n = chapter_of.get(eid)
        if lvl == 1 and n in PARTS:
            rows.append(f'<div class="part">{PARTS[n]}</div>')
        pg = PLACEHOLDER if pages is None else str(pages[len(pg_done)]).translate(FA)
        pg_done.append(eid)
        rows.append(
            f'<a class="row l{lvl}" href="#{eid}">'
            f'<span class="t">{title_html}</span>'
            f'<span class="dots"></span>'
            f'<span class="pg">{pg}</span></a>'
        )
    rows.append("</nav>")
    return "\n".join(rows)


def load_unit(path: Path) -> tuple[str, list, int]:
    """بارگذاری و تمیزسازی یک فایل HTML فصل.
    
    خروجی:
      (article_html, [(level, id, title_html, title_clean, pos), ...], number of headings)
    """
    from bs4 import BeautifulSoup

    num_m = re.match(r"^(\d+)-", path.name)
    num = int(num_m.group(1)) if num_m else 0
    anchor = f"chapter-{num:02d}"

    soup = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")

    # حذف بخش‌های اختصاصی وب و ناوبری
    for sel in REMOVE_SELECTORS:
        for node in soup.select(sel):
            node.decompose()

    for script in soup.find_all("script"):
        script.decompose()

    # غیرفعال‌سازی پیوندهای محلی file://
    for a in soup.find_all("a"):
        href = a.get("href", "")
        if isinstance(href, str) and href.startswith("file://"):
            a["href"] = "#"

    # حذف پیام‌های پیش‌فرض ترجمه
    for node in list(soup.find_all(string=True)):
        text = str(node)
        if "این صفحه از ترجمهٔ فارسی فصل‌های کتاب" in text and "راسل" in text:
            if node.parent:
                node.parent.decompose()

    # استخراج عنوان فصل
    entries = []
    pos = 0

    if num == 0:
        chapter_title_text = "پیشگفتار"
        chapter_title_html = "پیشگفتار"
    else:
        sub_node = soup.select_one(".subtitle")
        if sub_node:
            chapter_title_html = "".join(str(c) for c in sub_node.contents).strip()
            chapter_title_text = sub_node.get_text(" ", strip=True)
            sub_node.decompose()
        elif soup.title:
            chapter_title_html = soup.title.get_text(strip=True)
            chapter_title_text = chapter_title_html
        else:
            chapter_title_html = f"فصل {str(num).translate(FA)}"
            chapter_title_text = chapter_title_html

    entries.append((1, anchor, chapter_title_html, chapter_title_text, 0))

    # حذف پیام‌های ادامه یا پیوندهای پایان فصل
    for p in soup.find_all("p"):
        p_txt = p.get_text(strip=True)
        if "[ادامه:" in p_txt or "*[ادامه:" in p_txt:
            prev = p.find_previous_sibling()
            if prev and prev.name == "hr":
                prev.decompose()
            p.decompose()

    # شناسایی و استخراج بخش‌های H2
    used_ids = set()
    h2_idx = 0
    for h2 in soup.find_all("h2"):
        h2_text = h2.get_text(" ", strip=True)
        if not h2_text or h2_text == "پانوشت‌ها:":
            continue
        h2_idx += 1
        orig_id = h2.get("id")
        candidate = f"{anchor}-{orig_id}" if orig_id else f"{anchor}-h2-{h2_idx}"
        while candidate in used_ids:
            candidate = f"{candidate}-{h2_idx}"
        used_ids.add(candidate)
        h2["id"] = candidate
        pos += 1
        h2_html = "".join(str(c) for c in h2.contents).strip()
        entries.append((2, candidate, h2_html, h2_text, pos))

    # استخراج محتوای درون body یا .page
    container = soup.select_one(".page") or soup.body or soup
    body_content = "".join(str(c) for c in container.children if str(c).strip())

    article_html = (
        f'<article id="{anchor}" class="unit" dir="rtl" lang="fa">\n'
        f'  <h1 id="{anchor}">{chapter_title_html}</h1>\n'
        f"{body_content}\n"
        f'</article>'
    )

    return article_html, entries, pos + 1


def document(body: str, title: str, args) -> str:
    return (
        "<!DOCTYPE html>\n"
        f'<html lang="fa" dir="rtl"><head><meta charset="utf-8">'
        f'<base href="{HTML_DIR.as_uri()}/">'
        f"<title>{htmllib.escape(title)}</title>"
        f"<style>{css(args.page_size, args.font_size)}</style></head>"
        f'<body dir="rtl">\n{body}\n</body></html>'
    )


# ───────────────────────────── Rendering ─────────────────────────────
class Renderer:
    def __init__(self, args):
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        opts = {
            "args": [
                "--no-sandbox",
                "--disable-gpu",
                "--disable-dev-shm-usage",
                "--font-render-hinting=none",
            ]
        }

        # یافتن مسیر خودکار Chrome / Chromium
        chrome_cand = (
            args.chromium
            or os.environ.get("CHROMIUM_PATH")
            or shutil.which("google-chrome")
            or shutil.which("google-chrome-stable")
            or shutil.which("chromium")
            or shutil.which("chromium-browser")
        )
        if chrome_cand and os.path.exists(chrome_cand):
            opts["executable_path"] = chrome_cand

        try:
            self.browser = self._pw.chromium.launch(**opts)
        except Exception as e:
            self._pw.stop()
            sys.exit(
                f"Chromium/Chrome اجرا نشد: {e}\n"
                "راه‌حل: «playwright install chromium» را اجرا کنید یا مسیر Chrome را با --chromium مشخص کنید."
            )
        self.tmpdir = Path(tempfile.mkdtemp(prefix="aimapdf-"))

    def render(self, html: str, name: str) -> bytes:
        f = self.tmpdir / f"{name}.html"
        f.write_text(html, encoding="utf-8")
        page = self.browser.new_page()
        try:
            page.goto(f.as_uri(), wait_until="load", timeout=900_000)
            page.evaluate("document.fonts.ready")
            return page.pdf(
                prefer_css_page_size=True,
                print_background=True,
                outline=True,
                tagged=True,
            )
        finally:
            page.close()

    def close(self):
        try:
            self.browser.close()
            self._pw.stop()
        except Exception:
            pass
        if self.tmpdir.exists():
            shutil.rmtree(self.tmpdir, ignore_errors=True)


def get_toc_pages(doc, n_entries: int) -> list[int]:
    """استخراج شمارهٔ صفحات هدف پیوندهای فهرست از گذر نخست."""
    rows = []
    for pno in range(doc.page_count):
        links = [l for l in doc[pno].get_links() if l.get("page", -1) >= 0]
        if not links:
            continue
        links.sort(key=lambda l: (round(l["from"].y0, 0), -l["from"].x1))
        for l in links:
            key = (pno, round(l["from"].y0))
            if rows and rows[-1][0][0] == pno and abs(rows[-1][0][1] - key[1]) <= 2:
                continue
            rows.append((key, l["page"] + 1))
            if len(rows) == n_entries:
                break
        if len(rows) == n_entries:
            break
    if len(rows) != n_entries:
        raise RuntimeError(f"تعداد ردیف‌های فهرست ({n_entries}) با پیوندهای یافت‌شده ({len(rows)}) برابر نیست.")
    return [p for _, p in rows]


def count_toc_pages(doc, n_entries: int) -> int:
    """محاسبهٔ تعداد صفحات فهرست مطالب."""
    count = 0
    rows_found = 0
    for pno in range(1, doc.page_count):
        links = [l for l in doc[pno].get_links() if l.get("page", -1) >= 0]
        if not links:
            break
        count += 1
        rows_found += len(links)
        if rows_found >= n_entries:
            break
    return count


def finalize(pdf_bytes: bytes, out: Path, title: str, toc: list | None) -> int:
    import pymupdf

    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    if toc is not None:
        doc.set_toc(toc)
    doc.set_metadata({
        "title": title,
        "author": f"{AUTHORS} — ترجمهٔ فارسی",
        "subject": TITLE_EN,
        "creator": "build_pdf.py (Chromium + PyMuPDF)",
    })
    out.parent.mkdir(parents=True, exist_ok=True)
    doc.save(out, garbage=3, deflate=True)
    pages = doc.page_count
    doc.close()
    return pages


def outline_from_chromium(pdf_bytes: bytes, entries: list, n_heads: int) -> list:
    """ایجاد نشانک‌های تمیز فارسی برای یک فصل جداگانه."""
    import pymupdf

    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    raw = [it for it in doc.get_toc(simple=True) if it[0] <= 2]
    doc.close()
    if len(raw) != n_heads:
        return [[1, e[3], 1] for e in entries if e[0] == 1]
    return [[lvl, txt, 1 if pos is None else raw[pos][2]] for lvl, _, _, txt, pos in entries]


# ───────────────────────────── Builds ─────────────────────────────
def discover_chapters() -> list[tuple[int, Path]]:
    chapters = []
    for p in sorted(HTML_DIR.glob("*.html")):
        m = re.match(r"^(\d+)-", p.name)
        if m:
            chapters.append((int(m.group(1)), p))
    chapters.sort(key=lambda x: x[0])
    return chapters


def build_book(r: Renderer, args, version_info: dict):
    import pymupdf

    t0 = time.time()
    chapters = discover_chapters()
    arts, entries, chapter_of = [], [], {}

    front_cover_title = "روی جلد"
    front_cover_entry = (1, "front-cover", front_cover_title, front_cover_title, 0)
    cover_title = f"صفحهٔ اول: {TITLE_FA}"
    cover_entry = (1, "cover", cover_title, cover_title, 0)
    entries = [front_cover_entry, cover_entry]

    print(f"بارگذاری و آماده‌سازی {len(chapters)} فصل…", flush=True)
    for num, path in chapters:
        a, e, _ = load_unit(path)
        arts.append(a)
        entries += e
        chapter_of[f"chapter-{num:02d}"] = num

    body_gen = lambda pages: (
        cover_image_html()
        + "\n"
        + cover_html(version_info)
        + "\n"
        + toc_html(entries, chapter_of, pages)
        + "\n"
        + "\n".join(arts)
    )

    print("  گذر ۱: چیدمان اولیه و محاسبهٔ صفحات فهرست…", flush=True)
    pdf1 = r.render(document(body_gen(None), TITLE_FA, args), "book-pass1")
    d1 = pymupdf.open(stream=pdf1, filetype="pdf")
    pages = get_toc_pages(d1, len(entries))
    d1.close()

    print("  گذر ۲: درج شماره‌های صفحه در فهرست و نهایی‌سازی…", flush=True)
    pdf2 = r.render(document(body_gen(pages), TITLE_FA, args), "book-pass2")
    d2 = pymupdf.open(stream=pdf2, filetype="pdf")
    pages_pass2 = get_toc_pages(d2, len(entries))
    if pages_pass2 != pages:
        # در صورت جابه‌جایی جزئی، با یک گذر دیگر همگام‌سازی می‌شود
        pdf2 = r.render(document(body_gen(pages_pass2), TITLE_FA, args), "book-pass3")
        pages = pages_pass2

    # یافتن شمارهٔ صفحهٔ شروع فهرست مطالب برای نشانک PDF
    toc_start = 3
    for pno in range(d2.page_count):
        if len(d2[pno].get_links()) >= 5:
            toc_start = pno + 1
            break
    d2.close()

    toc = [
        [1, "روی جلد", 1],
        [1, cover_title, 2],
        [1, "فهرست مطالب", toc_start],
    ] + [
        [e[0], e[3], pages[i]] for i, e in enumerate(entries[2:], 2)
    ]
    out_file = PDF_DIR / "aima-4e-persian.pdf"
    n_pages = finalize(pdf2, out_file, TITLE_FA, toc)
    print(
        f"  ✓ {out_file.relative_to(ROOT)} — {n_pages} صفحه، {len(entries)} سرفصل در فهرست "
        f"({out_file.stat().st_size / 1e6:.1f} MB، {time.time() - t0:.0f} ثانیه)"
    )


def build_chapters(r: Renderer, args):
    sel = set(args.chapters) if args.chapters else None
    chapters = discover_chapters()
    chapters_dir = PDF_DIR / "chapters"
    chapters_dir.mkdir(parents=True, exist_ok=True)

    for num, path in chapters:
        if sel is not None and num not in sel:
            continue
        art, entries, n_heads = load_unit(path)
        art = art.replace('class="unit"', 'class="unit single"', 1)
        title = entries[0][3] if entries else f"فصل {num}"
        pdf = r.render(document(art, f"{title} — {TITLE_FA}", args), f"ch-{num:02d}")
        toc = outline_from_chromium(pdf, entries, n_heads)
        out = chapters_dir / f"chapter-{num:02d}.pdf"
        pages = finalize(pdf, out, f"{title} — {TITLE_FA}", toc)
        print(f"  ✓ {out.relative_to(ROOT)} — {pages} صفحه ({out.stat().st_size / 1e6:.1f} MB)", flush=True)


def main():
    ap = argparse.ArgumentParser(description="ساخت PDF کتاب AIMA 4e (با فهرست و نشانک) و PDF جداگانهٔ فصل‌ها")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--book-only", action="store_true", help="فقط ساخت کل کتاب (pdf/aima-4e-persian.pdf)")
    g.add_argument("--chapters-only", action="store_true", help="فقط ساخت PDF فصل‌ها")
    ap.add_argument("--chapters", type=int, nargs="+", metavar="N", help="فقط این فصل‌ها (0 = پیشگفتار)")
    ap.add_argument("--chromium", default=os.environ.get("CHROMIUM_PATH"),
                    help="مسیر Chrome/Chromium (پیش‌فرض: جستجوی خودکار سیستم یا Playwright)")
    ap.add_argument("--page-size", default="A4", help="اندازهٔ صفحه مانند A4 یا Letter (پیش‌فرض: A4)")
    ap.add_argument("--font-size", type=float, default=11, help="اندازهٔ قلم متن به pt (پیش‌فرض: 11)")
    ap.add_argument("--out-dir", type=Path, default=None, help="پوشهٔ خروجی (پیش‌فرض: pdf/)")
    args = ap.parse_args()

    if args.chapters:
        args.chapters_only = True
    if args.out_dir:
        global PDF_DIR
        PDF_DIR = args.out_dir.resolve()

    missing = [f for f in ("Vazirmatn-Regular.ttf", "Vazirmatn-Bold.ttf", "DejaVuSansMono.ttf")
               if not (FONTS_DIR / f).exists()]
    if missing:
        sys.exit(f"فونت‌ها در {FONTS_DIR} پیدا نشدند: {missing}")

    version_info = get_version_info()
    print("=" * 60)
    print(f"ساخت PDF کتاب {TITLE_FA}")
    print(f"نسخه: {version_info['version_num']} | کامیت: {version_info['commit_hash']}{version_info['dirty_flag']}")
    print(f"تاریخ: {version_info['jalali_date']} ({version_info['gregorian_date']})")
    print("=" * 60)

    r = Renderer(args)
    try:
        if not args.chapters_only:
            print("\nساخت کتاب کامل:")
            build_book(r, args, version_info)
        if not args.book_only:
            print("\nساخت PDF فصل‌ها:")
            build_chapters(r, args)
    finally:
        r.close()


if __name__ == "__main__":
    main()
