"""Keep a frozen Qt/SCIP process independent of a user's Python/Conda setup."""
import os
import sys

if getattr(sys, "frozen", False):
    # These are process-local changes. No persistent Windows settings are edited.
    for key in (
        "QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH", "QML2_IMPORT_PATH",
        "QML_IMPORT_PATH", "QTWEBENGINEPROCESS_PATH", "QTWEBENGINE_RESOURCES_PATH",
        "QTWEBENGINE_LOCALES_PATH", "PYTHONHOME", "PYTHONPATH", "SCIPOPTDIR",
    ):
        os.environ.pop(key, None)
