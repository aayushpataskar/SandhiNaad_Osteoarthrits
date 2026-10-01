"""Clinical report tab: per-knee result capture, live HTML preview, PDF export (EN / AS).

PDF engine: Qt WebEngine (Chromium, ships with PySide6) -> identical layout to the
OA-NER dashboard reports, with correct Assamese shaping. If QtWebEngine is missing,
falls back to reports.render.write_pdf (WeasyPrint / Playwright) or saves the HTML.
"""
import os
from datetime import datetime

from PySide6.QtCore import QUrl, QMarginsF
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox,
                               QFileDialog, QMessageBox, QTextBrowser)

from i18n import tr
from reports.render import build_html, load_i18n, write_pdf, available_languages, LANG_NAMES

try:
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from PySide6.QtGui import QPageLayout, QPageSize
    HAVE_WEBENGINE = True
except Exception:          # PySide6 without the Addons / WebEngine module
    HAVE_WEBENGINE = False

OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'sessions', 'reports')


class ReportPanel(QWidget):
    def __init__(self, get_context):
        """get_context(lang, knees_override=None) -> (context dict | None, message)."""
        super().__init__()
        self.get_context = get_context
        self.ui_lang = 'en'
        self.saved = {}                 # side -> knee dict
        self.live_knee = None           # callable returning current knee dict
        self._pending = []
        lay = QVBoxLayout(self)

        top = QHBoxLayout()
        self.lbl_lang = QLabel()
        self.lang = QComboBox()
        for code in available_languages():
            self.lang.addItem(LANG_NAMES.get(code, code), code)
        self.lang.currentIndexChanged.connect(self.refresh)
        self.btn_right = QPushButton()
        self.btn_left = QPushButton()
        self.btn_clear = QPushButton()
        self.btn_refresh = QPushButton()
        self.btn_export = QPushButton()
        self.btn_both = QPushButton()
        self.btn_right.clicked.connect(lambda: self._save('right'))
        self.btn_left.clicked.connect(lambda: self._save('left'))
        self.btn_clear.clicked.connect(self._clear)
        self.btn_refresh.clicked.connect(self.refresh)
        self.btn_export.clicked.connect(self.export_one)
        self.btn_both.clicked.connect(self.export_all)
        self.btn_export.setStyleSheet('background:#89b4fa; color:#11111b; font-weight:bold;')
        for w in (self.lbl_lang, self.lang, self.btn_right, self.btn_left, self.btn_clear):
            top.addWidget(w)
        top.addStretch()
        for w in (self.btn_refresh, self.btn_export, self.btn_both):
            top.addWidget(w)
        lay.addLayout(top)
        self.status = QLabel()
        self.status.setWordWrap(True)
        lay.addWidget(self.status)

        if HAVE_WEBENGINE:
            self.view = QWebEngineView()
            self.view.page().pdfPrintingFinished.connect(self._pdf_done)
        else:
            self.view = QTextBrowser()
        lay.addWidget(self.view, 1)
        self.retranslate('en')

    # ------------------------------------------------------------------
    def retranslate(self, lang):
        self.ui_lang = lang
        L = lambda k, **f: tr(k, lang, **f)  # noqa: E731
        self.lbl_lang.setText(L('sn.report.lang') + ':')
        self.btn_right.setText(L('sn.report.save_right'))
        self.btn_left.setText(L('sn.report.save_left'))
        self.btn_clear.setText(L('sn.report.clear'))
        self.btn_refresh.setText(L('sn.report.refresh'))
        self.btn_export.setText(L('sn.report.export'))
        self.btn_both.setText(L('sn.report.export_both'))
        i = self.lang.findData(lang)
        if i >= 0 and self.lang.currentIndex() != i:
            self.lang.blockSignals(True)      # report language follows UI language by default
            self.lang.setCurrentIndex(i)
            self.lang.blockSignals(False)
        self._update_status()

    def _update_status(self, extra=''):
        L = lambda k, **f: tr(k, self.ui_lang, **f)  # noqa: E731
        if self.saved:
            s = ', '.join(f"{side}: {len(k['probs'])} cycles" for side, k in self.saved.items())
        else:
            s = L('sn.report.none_saved')
        self.status.setText(f"<b>{L('sn.report.saved_knees')}:</b> {s}" + (f'<br>{extra}' if extra else ''))

    def _save(self, side):
        k = self.live_knee() if self.live_knee else None
        if not k:
            return
        k = dict(k, side=side)
        self.saved[side] = k
        if getattr(self, 'on_saved', None):
            self.on_saved(side)
        self._update_status()
        self.refresh()

    def _clear(self):
        self.saved.clear()
        self._update_status()
        self.refresh()

    def knees(self):
        if self.saved:
            return [self.saved[s] for s in ('right', 'left') if s in self.saved]
        k = self.live_knee() if self.live_knee else None
        return [k] if k else []

    def code(self):
        return self.lang.currentData() or 'en'

    def _html(self, code):
        ctx, msg = self.get_context(code, self.knees())
        if ctx is None:
            return None, msg
        return build_html(ctx, code), msg

    def refresh(self):
        html, msg = self._html(self.code())
        if html is None:
            self._update_status(f'<span style="color:#f9e2af">{msg}</span>')
            self.view.setHtml(f'<p style="font-family:sans-serif">{msg}</p>')
            return
        self._update_status(msg)
        path = self._write_html(html, 'preview_' + self.code())
        if HAVE_WEBENGINE:
            self.view.load(QUrl.fromLocalFile(path))
        else:
            self.view.setHtml(html)

    @staticmethod
    def _write_html(html, stem):
        os.makedirs(OUT_DIR, exist_ok=True)
        p = os.path.join(OUT_DIR, stem + '.html')
        with open(p, 'w', encoding='utf-8') as f:
            f.write(html)
        return p

    def _default_name(self, code):
        ctx, _ = self.get_context(code, self.knees())
        pid = ctx['patient']['id'] if ctx else 'report'
        return os.path.join(OUT_DIR, f"{pid}_{datetime.now():%Y%m%d_%H%M}_{code}.pdf")

    def export_one(self):
        code = self.code()
        path, _ = QFileDialog.getSaveFileName(self, 'PDF', self._default_name(code), 'PDF (*.pdf)')
        if path:
            self._export([(code, path)])

    def export_all(self):
        self._export([(c, self._default_name(c)) for c in available_languages()])

    def _export(self, jobs):
        for code, path in jobs:
            html, msg = self._html(code)
            if html is None:
                QMessageBox.warning(self, 'Report', msg)
                return
            os.makedirs(os.path.dirname(path), exist_ok=True)
            if HAVE_WEBENGINE:
                self._pending.append((html, path))
            else:
                used = write_pdf(html, path)
                shown = path if used != 'html-only' else os.path.splitext(path)[0] + '.html'
                self._update_status(tr('sn.report.no_webengine' if used == 'html-only' else 'sn.report.exported',
                                       self.ui_lang, path=shown))
        if HAVE_WEBENGINE:
            self._next_pdf()

    # sequential Qt printing: load page -> printToPdf -> pdfPrintingFinished -> next
    def _next_pdf(self):
        if not self._pending:
            self.refresh()
            return
        html, path = self._pending[0]
        src = self._write_html(html, os.path.splitext(os.path.basename(path))[0])
        page = self.view.page()

        def loaded(ok, page=page, path=path):
            page.loadFinished.disconnect(loaded)
            layout = QPageLayout(QPageSize(QPageSize.PageSizeId.A4), QPageLayout.Orientation.Portrait,
                                 QMarginsF(10, 10, 10, 12), QPageLayout.Unit.Millimeter)
            page.printToPdf(path, layout)
        page.loadFinished.connect(loaded)
        self.view.load(QUrl.fromLocalFile(src))

    def _pdf_done(self, path, ok):
        if self._pending:
            self._pending.pop(0)
        self._update_status(tr('sn.report.exported', self.ui_lang, path=path) if ok else f'PDF failed: {path}')
        self._next_pdf()
