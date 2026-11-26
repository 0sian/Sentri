"""Accuracy eval on one fixed screenshot. Ground-truth boxes (screen px) were read off the image by hand (+-5 px)."""
import sys, json
sys.path.insert(0, ".")
import som
from PIL import Image
S = sys.argv[1]; MODEL = sys.argv[2] if len(sys.argv) > 2 else "claude-sonnet-5-5"
img = Image.open(f"{S}/full.png").convert("RGB")
CASES = [
 ("the Copy button in the document panel header", (1117,73,1193,104)),
 ("the message input box at the bottom of the left chat", (100,1340,667,1377)),
 ("the close (X) button of the SENTRI HANDOFF document panel", (1267,73,1291,97)),
 ("the 'What Sentri is' heading", (735,690,860,712)),
 ("the 'Sonnet 5.5' model name at the bottom of the left chat", (480,1390,540,1408)),
 ("the SENTRI HANDOFF document card in the left chat", (93,849,613,912)),
 ("the 'auto mode on' status text at the bottom of the terminal", (1333,1390,1547,1408)),
 ("the speaker/volume icon in the thin left sidebar", (16,1317,43,1344)),
 ("the clock in the thin left sidebar", (13,1173,48,1283)),
 ("the red power button at the bottom of the left sidebar", (15,1397,44,1427)),
]
PAD = 14
def inside(p, b): return b[0]-PAD <= p[0] <= b[2]+PAD and b[1]-PAD <= p[1] <= b[3]+PAD
marks = som.gather(img, limit=300)
from collections import Counter; print(len(marks), "marks", dict(Counter(m["src"] for m in marks)))
scale = 0.75; im = som.render(img, marks, scale); im.save(f"{S}/som_eval.png")
raw_im = img.resize((int(img.width*scale), int(img.height*scale)))
cl = som.client(); res = {"som": 0, "raw": 0, "som_covered": 0}; rows = []
for q, gt in CASES:
    covered = any(inside(((m["box"][0]+m["box"][2])/2, (m["box"][1]+m["box"][3])/2), gt) for m in marks)
    res["som_covered"] += covered
    n, _ = som.ask_mark(cl, MODEL, im, marks, q)
    ok_som = bool(n) and 1 <= n <= len(marks) and inside(((marks[n-1]["box"][0]+marks[n-1]["box"][2])/2, (marks[n-1]["box"][1]+marks[n-1]["box"][3])/2), gt)
    p, _ = som.ask_raw(cl, MODEL, raw_im, q, scale)
    err = None if p is None else round(((p[0]-(gt[0]+gt[2])/2)**2 + (p[1]-(gt[1]+gt[3])/2)**2) ** .5)
    ok_raw = p is not None and inside(p, gt)
    res["som"] += ok_som; res["raw"] += ok_raw
    rows.append((q[:48], "box in marks" if covered else "NO BOX", f"SoM #{n} {'HIT' if ok_som else 'miss'}", f"raw err {err}px {'HIT' if ok_raw else 'miss'}"))
for r in rows: print(" | ".join(map(str, r)))
print(res, "of", len(CASES))
