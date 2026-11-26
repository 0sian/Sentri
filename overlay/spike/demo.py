"""End to end: screenshot -> model -> rope. usage: demo.py "<what to point at>" """
import sys, json, socket, os, time
sys.path.insert(0, ".")
import som
q = sys.argv[1]; sock = os.environ["XDG_RUNTIME_DIR"] + "/sentri-overlay.sock"
def send(m):
    s = socket.socket(socket.AF_UNIX); s.connect(sock); s.sendall((json.dumps(m) + "\n").encode()); s.recv(100); s.close()
send({"cmd": "clear"}); time.sleep(0.3)           # overlay must not be in the model's screenshot
img = som.grab("/tmp/demo_shot.png"); t = time.time()
p, u = som.ask_raw(som.client(), "claude-haiku-5-5", img, q, 1.0)
print("point", p, f"{time.time()-t:.1f}s", u.input_tokens, "in tokens")
if p: send({"cmd": "point", "x": p[0], "y": p[1]})
