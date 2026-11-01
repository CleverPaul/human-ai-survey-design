"""Offline desktop entry point. No web server or installed browser is used."""

from __future__ import annotations

import argparse
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import sys
import time

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, QUrl, Signal, Slot
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import (QWebEnginePage, QWebEngineProfile,
                                    QWebEngineSettings, QWebEngineUrlRequestInterceptor)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication, QFileDialog, QMainWindow, QMessageBox

from app import dispatch_api


ROOT = Path(__file__).resolve().parent
LOG = logging.getLogger("SurveyDesignLab")


def configure_logging():
    directory = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "SurveyDesignLab" / "logs"
    directory.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(directory / "desktop.log", maxBytes=1_000_000,
                                  backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    LOG.addHandler(handler)
    LOG.setLevel(logging.INFO)


class OfflineOnly(QWebEngineUrlRequestInterceptor):
    def interceptRequest(self, info):
        if info.requestUrl().scheme().lower() not in {"file", "qrc", "data", "blob", "about"}:
            info.block(True)


class Page(QWebEnginePage):
    def javaScriptConsoleMessage(self, level, message, line, source):
        LOG.info("JavaScript %s at %s:%s: %s", level, source, line, message)

    def acceptNavigationRequest(self, url, navigation_type, is_main_frame):
        # A desktop demonstration should stay on its bundled local page.
        return url.scheme() in {"file", "qrc", "data", "about"}


class TaskSignals(QObject):
    completed = Signal(str, str)


class ComputeTask(QRunnable):
    def __init__(self, request_id, path, body):
        super().__init__()
        self.request_id, self.path, self.body = request_id, path, body
        self.signals = TaskSignals()

    @Slot()
    def run(self):
        try:
            result = dispatch_api(self.path, self.body, backend="scip")
            envelope_json = json.dumps({"ok": True, "data": result},
                                       ensure_ascii=False, allow_nan=False)
        except Exception as exc:
            LOG.exception("Computation failed: %s", self.path)
            envelope_json = json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)
        self.signals.completed.emit(self.request_id, envelope_json)


class DesktopBridge(QObject):
    response = Signal(str, str)

    def __init__(self, window, test_export=None):
        super().__init__(window)
        self.window = window
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        self.tasks = {}
        self.test_export = test_export
        self.requests = []

    @Slot(str, str, str)
    def request(self, request_id, path, payload_json):
        try:
            if len(payload_json) > 2_000_000:
                raise ValueError("Request is too large.")
            body = json.loads(payload_json)
            self.requests.append(path)
            if path == "/desktop/save":
                result = self.save_json(body)
                self.response.emit(request_id, json.dumps({"ok": True, "data": result}))
                return
            if len(self.tasks) >= 4:
                raise ValueError("A computation is already in progress. Please wait.")
            task = ComputeTask(request_id, path, body)
            task.signals.completed.connect(self.complete)
            self.tasks[request_id] = task
            self.pool.start(task)
        except Exception as exc:
            self.response.emit(request_id, json.dumps({"ok": False, "error": str(exc)}))

    @Slot(str, str)
    def complete(self, request_id, envelope):
        self.tasks.pop(request_id, None)
        self.response.emit(request_id, envelope)

    def save_json(self, body):
        if not isinstance(body, dict):
            raise ValueError("Invalid export request.")
        content = body.get("content")
        # Frontend supplies serialized JSON; parse it before writing to disk.
        parsed = json.loads(content) if isinstance(content, str) else content
        data = json.dumps(parsed, ensure_ascii=False, indent=2, allow_nan=False)
        filename = Path(str(body.get("filename", "survey-design.json"))).name
        if self.test_export:
            destination = str(self.test_export)
        else:
            dialog = QFileDialog(self.window, "Save simulation results")
            dialog.setAcceptMode(QFileDialog.AcceptSave)
            dialog.setNameFilter("JSON results (*.json)")
            dialog.setDefaultSuffix("json")
            dialog.setDirectory(str(Path.home() / "Documents"))
            dialog.selectFile(filename)
            destination = dialog.selectedFiles()[0] if dialog.exec() else ""
        if not destination:
            return {"saved": False}
        path = Path(destination)
        path.write_text(data + "\n", encoding="utf-8")
        return {"saved": True, "path": str(path)}


class Window(QMainWindow):
    def __init__(self, test_export=None):
        super().__init__()
        self.setWindowTitle("Survey Design Lab")
        self.resize(1360, 940)
        self.setMinimumSize(950, 680)
        self.view = QWebEngineView(self)
        self.profile = QWebEngineProfile(self)
        self.interceptor = OfflineOnly(self.profile)
        self.profile.setUrlRequestInterceptor(self.interceptor)
        self.page = Page(self.profile, self.view)
        self.view.setPage(self.page)
        self.page.settings().setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, False)
        self.page.settings().setAttribute(QWebEngineSettings.JavascriptCanOpenWindows, False)
        self.bridge = DesktopBridge(self, test_export)
        self.channel = QWebChannel(self.page)
        self.channel.registerObject("desktopBridge", self.bridge)
        self.page.setWebChannel(self.channel)
        self.setCentralWidget(self.view)
        self.view.loadFinished.connect(self.loaded)
        self.view.setUrl(QUrl.fromLocalFile(str(ROOT / "web" / "index.html")))

    def loaded(self, success):
        if not success:
            LOG.error("Bundled interface could not load")
            QMessageBox.critical(self, "Survey Design Lab", "The bundled interface could not load.")


class SelfTest(QObject):
    """Exercise the real QWebChannel, frontend and solver in a frozen build."""
    def __init__(self, application, window, report, screenshot):
        super().__init__(window)
        self.application, self.window = application, window
        self.report, self.screenshot = report, screenshot
        self.start = time.monotonic()
        self.phase = "initial"
        self.data = {"frozen": bool(getattr(sys, "frozen", False)), "executable": sys.executable}
        self.timer = QTimer(self)
        self.timer.setInterval(400)
        self.timer.timeout.connect(self.poll)
        self.timer.start()
        self.pending = False

    def poll(self):
        if time.monotonic() - self.start > 115:
            self.finish("Desktop test timed out.")
            return
        if self.pending:
            return
        self.pending = True
        self.window.page.runJavaScript("""JSON.stringify({
          desktop: !!window.SurveyDesktop?.isDesktop,
          busy: typeof state === 'undefined' || state.busy,
          scenario: typeof state === 'undefined' ? null : state.scenario,
          result: typeof state === 'undefined' ? null : state.result,
          frontier: typeof state === 'undefined' ? null : state.frontier,
          svgCount: document.querySelectorAll('svg').length,
          status: document.getElementById('status')?.textContent,
          url: location.href
        })""", self.observed)

    def observed(self, value):
        self.pending = False
        try:
            snapshot = json.loads(value or "null")
            if not snapshot or snapshot["busy"] or not snapshot["result"]:
                return
            if snapshot["result"].get("objective") is None:
                raise RuntimeError(snapshot["status"])
            if self.phase == "initial":
                assert snapshot["desktop"] and snapshot["url"].startswith("file:")
                assert snapshot["svgCount"] >= 2
                assert "SCIP" in snapshot["result"]["solver"]
                self.data["initial"] = snapshot
                self.phase = "interaction"
                self.window.page.runJavaScript("""
                  document.querySelector('[data-view="weights"]').click();
                  document.querySelector('[data-group="1"]').click();
                  document.getElementById('budget').value = '4';
                  labels(); document.getElementById('optimize').click();
                """)
            elif self.phase == "interaction":
                if snapshot["result"]["budget"] != 4:
                    return
                self.data["interaction"] = snapshot
                self.phase = "export"
                self.window.page.runJavaScript("document.getElementById('download').click()")
            elif self.phase == "export":
                if not self.window.bridge.test_export.exists():
                    return
                export = json.loads(self.window.bridge.test_export.read_text(encoding="utf-8"))
                assert len(export["scenario"]["Q"]) == 20
                assert export["solution"]["budget"] == 4
                self.data["export"] = {"path": str(self.window.bridge.test_export),
                                       "matrix_dimension": len(export["scenario"]["Q"])}
                self.phase = "frontier"
                self.window.page.runJavaScript("""
                  document.getElementById('frontier-details').open = true;
                  document.getElementById('frontier').click();
                """)
            elif self.phase == "frontier":
                if not snapshot["frontier"]:
                    return
                assert len(snapshot["frontier"]["points"]) == 8
                self.data["frontier"] = snapshot["frontier"]
                if self.screenshot:
                    self.window.grab().save(str(self.screenshot))
                self.finish()
        except Exception as exc:
            self.finish(str(exc) or type(exc).__name__)

    def finish(self, error=None):
        self.timer.stop()
        self.data.update(ok=error is None, error=error,
                         elapsed_seconds=time.monotonic() - self.start,
                         requests=self.window.bridge.requests)
        self.report.parent.mkdir(parents=True, exist_ok=True)
        self.report.write_text(json.dumps(self.data, ensure_ascii=False, indent=2, allow_nan=False),
                               encoding="utf-8")
        self.application.exit(0 if error is None else 1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", type=Path, metavar="REPORT_JSON")
    parser.add_argument("--screenshot", type=Path)
    options = parser.parse_args()
    configure_logging()
    application = QApplication([sys.argv[0]])
    application.setApplicationName("Survey Design Lab")
    application.setOrganizationName("SurveyDesignLab")
    test_export = options.self_test.with_suffix(".run.json") if options.self_test else None
    if test_export:
        test_export.parent.mkdir(parents=True, exist_ok=True)
        test_export.unlink(missing_ok=True)
    window = Window(test_export)
    window.show()
    if options.self_test:
        window.self_test = SelfTest(application, window, options.self_test, options.screenshot)
    LOG.info("Desktop started; frozen=%s", bool(getattr(sys, "frozen", False)))
    code = application.exec()
    window.bridge.pool.waitForDone()
    LOG.info("Desktop closed; exit=%s", code)
    # Dispose the page before its off-the-record profile.
    window.view.setPage(None)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
