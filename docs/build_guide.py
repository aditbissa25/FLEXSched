"""Build docs/PROJECT_GUIDE.md (and the PDF) from docs/guide/*.md.

The guide's chapters contain markers like

    <!-- include: engine/src/fatigue.cpp -->

which are replaced by the CURRENT contents of that file, so the code shown in
the guide can never drift from the code in the repository.

Usage:
    python docs/build_guide.py            # Markdown only
    python docs/build_guide.py --pdf      # Markdown + PDF (needs: pip install markdown pygments,
                                          #                 and Microsoft Edge or Google Chrome)
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

DOCS = Path(__file__).resolve().parent
ROOT = DOCS.parent
CHAPTERS = DOCS / "guide"
OUT_MD = DOCS / "PROJECT_GUIDE.md"
OUT_PDF = DOCS / "PROJECT_GUIDE.pdf"

INCLUDE = re.compile(r"^<!-- include: (\S+) -->$", re.MULTILINE)
LANG = {".cpp": "cpp", ".hpp": "cpp", ".py": "python", ".sql": "sql", ".toml": "toml",
        ".yml": "yaml", ".json": "json", ".txt": "cmake", ".md": "markdown"}


def _fence(rel_path: str) -> str:
    path = ROOT / rel_path
    if not path.is_file():
        raise FileNotFoundError(f"include target not found: {rel_path}")
    lang = LANG.get(path.suffix, "text")
    code = path.read_text(encoding="utf-8").rstrip("\n")
    return f"**File: `{rel_path}`**\n\n```{lang}\n{code}\n```\n"


def build_markdown() -> str:
    parts = [p.read_text(encoding="utf-8") for p in sorted(CHAPTERS.glob("*.md"))]
    text = "\n".join(parts)
    text = INCLUDE.sub(lambda m: _fence(m.group(1)), text)
    header = ("<!-- GENERATED FILE: edit docs/guide/*.md and run "
              "`python docs/build_guide.py --pdf` -->\n\n")
    return header + text


CSS = """
@page { size: A4; margin: 16mm 14mm; }
body { font-family: 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; font-size: 10.5pt;
       line-height: 1.5; color: #1f2328; max-width: 100%; }
h1 { font-size: 21pt; border-bottom: 2px solid #0b5cad; padding-bottom: 4px; color: #0b3d75;
     page-break-before: always; margin-top: 0; }
h1:first-of-type { page-break-before: avoid; }
h2 { font-size: 15pt; color: #0b3d75; border-bottom: 1px solid #d0d7de; padding-bottom: 2px;
     margin-top: 22px; }
h3 { font-size: 12pt; color: #1f2328; margin-top: 16px; }
h2, h3 { page-break-after: avoid; }
code { font-family: Consolas, 'Cascadia Mono', Menlo, monospace; font-size: 9pt;
       background: #f3f4f6; padding: 1px 4px; border-radius: 3px; }
pre { background: #f6f8fa; border: 1px solid #d0d7de; border-radius: 6px; padding: 8px 10px;
      font-size: 8.3pt; line-height: 1.35; white-space: pre-wrap; word-wrap: break-word; }
pre code { background: none; padding: 0; font-size: 8.3pt; }
table { border-collapse: collapse; margin: 8px 0; font-size: 9.5pt; page-break-inside: avoid; }
th, td { border: 1px solid #d0d7de; padding: 4px 8px; vertical-align: top; }
th { background: #eef3fa; }
blockquote { border-left: 4px solid #0b5cad; margin: 8px 0; padding: 4px 12px;
             background: #f5f9ff; color: #24292f; }
hr { border: none; border-top: 1px solid #d0d7de; margin: 18px 0; }
.codehilite { background: #f6f8fa; }
"""


def build_pdf(markdown_text: str) -> Path:
    import markdown  # imported lazily: only needed for the PDF
    from pygments.formatters import HtmlFormatter

    body = markdown.markdown(
        markdown_text,
        extensions=["fenced_code", "tables", "codehilite", "sane_lists"],
        extension_configs={"codehilite": {"guess_lang": False, "css_class": "codehilite"}},
    )
    style = CSS + HtmlFormatter(style="friendly").get_style_defs(".codehilite")
    html = (f"<!doctype html><html><head><meta charset='utf-8'>"
            f"<title>FLEXSched - Project Guide</title><style>{style}</style></head>"
            f"<body>{body}</body></html>")

    browser = _find_browser()
    OUT_PDF.unlink(missing_ok=True)
    # A private profile directory forces a NEW headless browser process
    # (otherwise an already-open browser may swallow the request). It lives in
    # the git-ignored build/ folder because long temp paths break Chromium.
    profile = ROOT / "build" / "pdf-profile"
    profile.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        html_path = Path(tmp) / "guide.html"
        html_path.write_text(html, encoding="utf-8")
        subprocess.run([browser, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                        f"--user-data-dir={profile}",
                        f"--print-to-pdf={OUT_PDF}", html_path.as_uri()],
                       check=True, capture_output=True, timeout=300)
    if not OUT_PDF.is_file():
        raise RuntimeError("the browser did not produce a PDF")
    return OUT_PDF


def _find_browser() -> str:
    candidates = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    ]
    for name in ("msedge", "google-chrome", "chromium", "chromium-browser", "chrome"):
        found = shutil.which(name)
        if found:
            candidates.insert(0, found)
    for c in candidates:
        if Path(c).is_file():
            return c
    raise FileNotFoundError("Microsoft Edge or Google Chrome is needed to render the PDF")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pdf", action="store_true", help="also render PROJECT_GUIDE.pdf")
    args = parser.parse_args()

    text = build_markdown()
    OUT_MD.write_text(text, encoding="utf-8")
    print(f"wrote {OUT_MD.relative_to(ROOT)} ({len(text.splitlines())} lines)")
    if args.pdf:
        print(f"wrote {build_pdf(text).relative_to(ROOT)}")


if __name__ == "__main__":
    main()
