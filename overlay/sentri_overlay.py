#!/usr/bin/env python3
"""Sentri guide overlay: click-through fullscreen layer + notch bubble (Qt6/QML + layer-shell-qt).

Runs as its own process so Qt never touches the asyncio daemon. Control: JSON lines on the unix
socket $XDG_RUNTIME_DIR/sentri-overlay.sock (see overlay/README.md).
"""
import json
import os
import sys
from pathlib import Path

from PyQt6.QtCore import QObject, QUrl, pyqtSignal, pyqtSlot, QTimer
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtNetwork import QLocalServer
from PyQt6.QtQml import QQmlApplicationEngine

HERE = Path(__file__).resolve().parent
SOCK = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "sentri-overlay.sock"


class Bridge(QObject):
    """Commands in from the socket, state out to QML."""
    command = pyqtSignal(str, "QVariant")      # cmd name, args dict

    def __init__(self):
        super().__init__()
        self.server = QLocalServer(self)
        QLocalServer.removeServer(str(SOCK))
        self.server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        if not self.server.listen(str(SOCK)):
            raise SystemExit(f"cannot listen on {SOCK}: {self.server.errorString()}")
        self.server.newConnection.connect(self._accept)

    def _accept(self):
        while (c := self.server.nextPendingConnection()):
            buf = bytearray()
            c.readyRead.connect(lambda c=c, buf=buf: self._read(c, buf))
            c.disconnected.connect(c.deleteLater)

    def _read(self, c, buf):
        buf += bytes(c.readAll())
        while b"\n" in buf:
            line, _, rest = bytes(buf).partition(b"\n")
            buf[:] = rest
            try:
                m = json.loads(line)
                cmd = str(m.pop("cmd"))
            except Exception:
                c.write(b'{"ok":false,"err":"bad json"}\n')
                continue
            self.command.emit(cmd, m)
            c.write(b'{"ok":true}\n')

    @pyqtSlot(result=str)
    def socketPath(self):
        return str(SOCK)

    @pyqtSlot()
    def quit(self):
        QGuiApplication.quit()


def main():
    os.environ.setdefault("QT_QPA_PLATFORM", "wayland")
    app = QGuiApplication(sys.argv)
    app.setApplicationName("sentri-overlay")
    engine = QQmlApplicationEngine()
    engine.warnings.connect(lambda ws: [print('qml:', w.toString(), file=sys.stderr) for w in ws])
    bridge = Bridge()
    engine.rootContext().setContextProperty("bridge", bridge)
    engine.load(QUrl.fromLocalFile(str(HERE / "Main.qml")))
    if not engine.rootObjects():
        return 1
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
