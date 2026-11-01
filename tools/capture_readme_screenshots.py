"""Capture the real offline Qt interface for the repository README.

Run with the desktop build environment. No HTTP server, browser installation,
data substitution, or changes to the application's HTML/CSS are used.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--output", type=Path)
parser.add_argument("--visible", action="store_true", help="Use a visible Qt window if the offscreen platform is unavailable")
args = parser.parse_args()
if not args.visible:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_SCALE_FACTOR", "1")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --disable-background-networking")

CODE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(CODE))
from PySide6.QtCore import QObject, QRect, QTimer
from PySide6.QtWidgets import QApplication
from desktop_app import Window


class Capture(QObject):
    def __init__(self, application, window, output):
        super().__init__(window)
        self.application, self.window, self.output = application, window, output
        self.started = time.monotonic()
        self.phase = "initial"
        self.pending = False
        self.record = {"method": "QWebEngineView.grab of the real local desktop interface", "screenshots": []}
        self.timer = QTimer(self)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self.poll)
        self.timer.start()

    def poll(self):
        if time.monotonic() - self.started > 180:
            self.finish("Screenshot capture timed out.")
            return
        if self.pending:
            return
        self.pending = True
        self.window.page.runJavaScript("""JSON.stringify({
          ready: typeof state !== 'undefined' && !!state.scenario && !!state.result && !state.busy,
          result: typeof state === 'undefined' ? null : state.result,
          config: typeof state === 'undefined' ? null : state.scenario?.config,
          frontier: typeof state === 'undefined' ? null : state.frontier,
          height: document.documentElement.scrollHeight,
          status: document.getElementById('status')?.textContent,
          url: location.href
        })""", self.observed)

    def observed(self, raw):
        self.pending = False
        try:
            data = json.loads(raw or "null")
            if not data or not data["ready"]:
                return
            if data["result"].get("objective") is None:
                raise RuntimeError(data["status"])
            if self.phase == "initial":
                self.record["scenario"] = data["config"]
                self.record["solution"] = data["result"]
                self.record["transport"] = "QWebChannel with local file:// assets"
                self.phase = "overview"
                self.resize(1280, int(data["height"]))
                self.window.page.runJavaScript("window.scrollTo(0, 0)")
                QTimer.singleShot(650, lambda: self.capture("overview.png", None, self.show_bias))
            elif self.phase == "frontier" and data["frontier"]:
                self.record["frontier"] = data["frontier"]
                self.phase = "design-capture"
                self.resize(1280, int(data["height"]))
                self.window.page.runJavaScript("window.scrollTo(0, 0)")
                QTimer.singleShot(650, lambda: self.capture(
                    "optimized-design-and-frontier.png",
                    "(() => { const a = document.getElementById('metrics').getBoundingClientRect(); const b = document.getElementById('frontier-details').getBoundingClientRect(); return {x:a.x-2,y:a.y-2,width:a.width+4,height:b.bottom-a.y+4}; })()",
                    lambda: self.finish(None)))
        except Exception as exc:
            self.finish(str(exc))

    def resize(self, width, height):
        self.window.view.setFixedSize(width, height)
        self.window.adjustSize()

    def capture(self, filename, rectangle_script, next_step):
        if rectangle_script is None:
            self.save(filename, None, next_step)
        else:
            self.window.page.runJavaScript("JSON.stringify(" + rectangle_script + ")", lambda raw: self.save(filename, json.loads(raw), next_step))

    def save(self, filename, bounds, next_step):
        try:
            rectangle = self.window.view.rect() if bounds is None else QRect(
                round(bounds["x"]), round(bounds["y"]), round(bounds["width"]), round(bounds["height"]))
            rectangle = rectangle.intersected(self.window.view.rect())
            pixmap = self.window.view.grab(rectangle)
            if pixmap.isNull() or not pixmap.save(str(self.output / filename), "PNG"):
                raise RuntimeError(f"Unable to save {filename}")
            self.record["screenshots"].append({"file": filename, "width": pixmap.width(), "height": pixmap.height(), "viewport_region": bounds})
            next_step()
        except Exception as exc:
            self.finish(str(exc))

    def show_bias(self):
        self.phase = "bias"
        self.resize(1280, 1000)
        self.window.page.runJavaScript("""
          document.querySelector('[data-group="1"]').click();
          state.probe = 72; renderBias();
          document.querySelector('.bias-card').scrollIntoView({block:'center'});
        """)
        QTimer.singleShot(650, lambda: self.capture(
            "bias-and-uncertainty.png",
            "(() => { const b=document.querySelector('.bias-card').getBoundingClientRect(); return {x:b.x-2,y:b.y-2,width:b.width+4,height:b.height+4}; })()",
            self.show_design))

    def show_design(self):
        self.phase = "frontier"
        self.window.page.runJavaScript("""
          document.querySelector('[data-view="weights"]').click();
          document.getElementById('frontier-details').open = true;
          document.getElementById('frontier').click();
        """)

    def finish(self, error):
        self.timer.stop()
        self.record["error"] = error
        (self.output / "capture.json").write_text(json.dumps(self.record, indent=2, ensure_ascii=False), encoding="utf-8")
        print(json.dumps({"error": error, "screenshots": self.record["screenshots"]}), flush=True)
        self.application.exit(1 if error else 0)


output = (args.output or CODE / "docs" / "screenshots").resolve()
output.mkdir(parents=True, exist_ok=True)
application = QApplication([sys.argv[0]])
window = Window()
window.view.setFixedSize(1280, 1000)
window.adjustSize()
window.show()
capture = Capture(application, window, output)
sys.exit(application.exec())
