"""Collect QtQml DLL dependencies, without unrelated QML application modules.

The app renders a local HTML document in QWebEngineWidgets and never imports
QML. QtQml/QtQuick DLLs are still WebEngine dependencies; an entire QML module
tree (3D, multimedia, location, etc.) is not.
"""
from PyInstaller.utils.hooks.qt import add_qt6_dependencies

hiddenimports, binaries, datas = add_qt6_dependencies(__file__)
