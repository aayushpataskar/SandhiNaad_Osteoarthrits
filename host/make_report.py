"""Command-line report rendering (no GUI needed).

  python make_report.py --lang as --variant moderate --out sample_as.pdf
  python make_report.py --lang en --variant high --out sample_en.pdf

Uses the OA-NER sample fixtures (reports/fixtures/samples.json). In the app,
reports are built from the real session instead (Clinical Report tab).
Back-end: WeasyPrint (set SANDHINAAD_GTK_BIN on Windows) -> Playwright/Chromium ->
HTML only (open it in Chrome/Edge and Print -> Save as PDF).
"""
import argparse
import sys

from reports.render import build_html, load_fixture, write_pdf, available_languages


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--lang', default='en', choices=available_languages())
    ap.add_argument('--variant', default='moderate', choices=['low', 'moderate', 'high', 'indeterminate'])
    ap.add_argument('--simulated', action='store_true')
    ap.add_argument('--out', default='sample_report.pdf')
    ap.add_argument('--backend', default='auto', choices=['auto', 'weasyprint', 'chromium'])
    a = ap.parse_args()
    ctx = load_fixture(a.variant)
    if a.simulated:
        ctx['screening']['data_source'] = 'simulated'
    used = write_pdf(build_html(ctx, a.lang), a.out, a.backend)
    print(f'{a.out}: rendered with {used}' if used != 'html-only'
          else f'No PDF engine found - wrote {a.out[:-4]}.html (print it to PDF from a browser)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
