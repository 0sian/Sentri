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
from PyQt6.QtGui import QGuiApplication, QRegion
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
        self.subscribers = []      # connections that sent {"cmd":"subscribe"}: they get events back

    def start(self):
        """Listen only once the QML is loaded: a command that arrived earlier would be acknowledged
        and then dropped (nothing is connected to the signal yet)."""
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
            if cmd == "subscribe":     # the daemon keeps this connection open to hear button presses
                if c not in self.subscribers:
                    self.subscribers.append(c)
                    c.disconnected.connect(lambda c=c: self.subscribers.remove(c) if c in self.subscribers else None)
            else:
                self.command.emit(cmd, m)
            c.write(b'{"ok":true}\n')

    @pyqtSlot(str)
    def send_event(self, line: str):
        """An event for the daemon (e.g. a notch button press): one JSON line to each subscriber."""
        for c in list(self.subscribers):
            c.write(line.encode() + b"\n")
            c.flush()

    @pyqtSlot(QObject, int, int, int, int)
    def setMask(self, win, x, y, w, h):
        """Limit a window's input region to a rectangle (Qt sends it to the compositor), so the
        transparent rest of a fixed-size window lets clicks through."""
        win.setMask(QRegion(x, y, w, h))

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
    # real QScreen objects: QML's Qt.application.screens are QQuickScreenInfo wrappers that can't be
    # assigned to Window.screen or the layer-shell screen property
    engine.rootContext().setContextProperty("screenList", app.screens())
    engine.load(QUrl.fromLocalFile(str(HERE / "Main.qml")))
    if not engine.rootObjects():
        return 1
    bridge.start()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
