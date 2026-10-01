"""
reports/render.py — Multilingual A4 clinical screening report (HTML -> PDF).

Ported from the OA-NER dashboard (reports/render.py) and extended for SandhiNaad.
The HTML template, CSS, fonts and translations are shared; only the PDF
back-end differs:

  * In the desktop app: Qt WebEngine (Chromium) — no extra install needed.
    See ui/report_panel.py (asynchronous, needs the Qt event loop).
  * From the command line (python -m reports.make_report):
      1. WeasyPrint, if installed (on Windows it needs GTK3; set SANDHINAAD_GTK_BIN
         to the gtk3\\bin folder, e.g. the one inside the OA-NER dashboard folder)
      2. Playwright + Chromium, if installed
      3. otherwise the .html is written and can be printed to PDF from any browser.

Languages: every <lang>.json in reports/i18n (currently 'en' and 'as').
Add a language by copying en.json -> xx.json, translating the values, and adding
a Noto font for its script to fonts/ + the @font-face list in the template.
"""
from __future__ import annotations

import copy
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict

import jinja2

_DIR = Path(__file__).resolve().parent
_FONTS = _DIR / "fonts"
_TEMPLATES = _DIR / "templates"
_STATIC = _DIR / "static"
_I18N = _DIR / "i18n"
_FIXTURES = _DIR / "fixtures"

LANG_NAMES = {"en": "English", "as": "অসমীয়া (Assamese)"}

_env = jinja2.Environment(loader=jinja2.FileSystemLoader(str(_TEMPLATES)),
                          autoescape=jinja2.select_autoescape(["html", "xml"]))


def available_languages():
    return [p.stem for p in sorted(_I18N.glob("*.json"))]


def load_i18n(lang: str = "en") -> Dict[str, Any]:
    f = _I18N / f"{lang}.json"
    if not f.exists():
        f = _I18N / "en.json"
    with open(f, encoding="utf-8") as fh:
        return json.load(fh)


def load_fixture(variant: str = "moderate") -> Dict[str, Any]:
    with open(_FIXTURES / "samples.json", encoding="utf-8") as fh:
        s = json.load(fh)
    return copy.deepcopy(s.get(variant, s["moderate"]))


def localize(ctx: Dict[str, Any], t: Dict[str, Any]) -> Dict[str, Any]:
    """Fill advice / referral text from the chosen language (tier-driven)."""
    ctx = copy.deepcopy(ctx)
    tier = ctx.get("advice", {}).get("tier", "moderate")
    if tier in t.get("advice", {}):
        ctx.setdefault("advice", {})["items"] = t["advice"][tier]
    key = ctx.get("referral", {}).get("key") or {
        "low": "routine", "moderate": "phc_review", "high": "priority_chc",
        "indeterminate": "technical_retake"}.get(tier, "phc_review")
    if key in t.get("referral", {}):
        ctx.setdefault("referral", {})["recommended_action"] = t["referral"][key]
    return ctx


def build_html(context: Dict[str, Any], lang: str = "en", is_simulated: bool = False) -> str:
    t = load_i18n(lang)
    ctx = localize(context, t)
    css = (_STATIC / "report.css").read_text(encoding="utf-8")
    return _env.get_template("report.html").render(
        data=ctx, t=t, lang=lang, font_dir=_FONTS.as_uri(), css_content=css,
        is_simulated=is_simulated or ctx.get("screening", {}).get("data_source") == "simulated")


# --------------------------------------------------------------------------- CLI back-ends
def _weasyprint_pdf(html: str, out: Path) -> bool:
    gtk = os.environ.get("SANDHINAAD_GTK_BIN")
    if gtk and sys.platform.startswith("win") and Path(gtk).exists():
        os.environ["PATH"] = gtk + os.pathsep + os.environ.get("PATH", "")
        if hasattr(os, "add_dll_directory"):
            os.add_dll_directory(gtk)
    try:
        import weasyprint  # noqa: WPS433
    except Exception:
        return False
    weasyprint.HTML(string=html, base_url=str(_DIR)).write_pdf(str(out))
    return True


def _chromium_pdf(html: str, out: Path) -> bool:
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return False
    tmp = out.with_suffix(".html")
    tmp.write_text(html, encoding="utf-8")
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        pg.goto(tmp.resolve().as_uri())
        pg.wait_for_timeout(300)
        pg.pdf(path=str(out), format="A4", print_background=True,
               margin={"top": "10mm", "bottom": "12mm", "left": "10mm", "right": "10mm"})
        b.close()
    return True


def write_pdf(html: str, out_path: str | Path, backend: str = "auto") -> str:
    """Returns the backend used ('weasyprint' | 'chromium' | 'html-only')."""
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    if backend in ("auto", "weasyprint") and _weasyprint_pdf(html, out):
        return "weasyprint"
    if backend in ("auto", "chromium") and _chromium_pdf(html, out):
        return "chromium"
    out.with_suffix(".html").write_text(html, encoding="utf-8")
    return "html-only"
