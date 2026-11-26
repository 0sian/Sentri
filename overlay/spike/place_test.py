"""Drive the running overlay through edge/corner targets and grab a screenshot of each."""
import json, os, socket, subprocess, sys, time
sock = os.environ["XDG_RUNTIME_DIR"] + "/sentri-overlay.sock"; out = sys.argv[1]
def send(m):
    s = socket.socket(socket.AF_UNIX); s.connect(sock); s.sendall((json.dumps(m) + "\n").encode()); s.recv(100); s.close()
send({"cmd": "debug", "on": False})
T = [(2500, 60), (60, 1380), (1300, 90), (2500, 1400), (1280, 720), (40, 40)]
for i, (x, y) in enumerate(T, 1):
    send({"cmd": "point", "x": x, "y": y, "title": f"Step {i}", "text": "Click the highlighted button to open the settings panel, then pick Display from the list on the left."})
    time.sleep(3.2); subprocess.run(["grim", "-s", "0.4", f"{out}/c{i}.png"])
