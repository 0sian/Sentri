"""Pointing spike: mark detection (OCR + AT-SPI [+ OpenCV if installed]), set-of-marks rendering,
and model queries (set-of-marks vs raw coordinates)."""
import base64, io, json, subprocess, sys, tomllib
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

def grab(path):
    subprocess.run(["grim", str(path)], check=True)
    return Image.open(path).convert("RGB")

# ---------- mark sources ----------
def marks_ocr(img, min_conf=45):
    out = subprocess.run(["tesseract", "stdin", "stdout", "--psm", "11", "tsv"], input=_png(img),
                         capture_output=True, check=True).stdout.decode()
    rows = [r.split("\t") for r in out.splitlines()[1:]]
    words = []
    for r in rows:
        if len(r) < 12 or not r[11].strip() or float(r[10]) < min_conf: continue
        x, y, w, h = map(int, r[6:10]); words.append((x, y, x + w, y + h, r[11]))
    words.sort(key=lambda b: (b[1] // 12, b[0]))
    lines = []
    for w in words:   # merge words on the same row that are close together
        for L in lines:
            if abs((L[1] + L[3]) / 2 - (w[1] + w[3]) / 2) < 8 and 0 <= w[0] - L[2] < 1.2 * (w[3] - w[1]) + 6:
                L[0] = min(L[0], w[0]); L[1] = min(L[1], w[1]); L[2] = max(L[2], w[2]); L[3] = max(L[3], w[3])
                L[4] += " " + w[4]; break
        else:
            lines.append(list(w))
    return [dict(box=tuple(L[:4]), src="ocr", text=L[4]) for L in lines if L[2] - L[0] > 8]

def marks_atspi():
    try:
        import gi; gi.require_version("Atspi", "2.0"); from gi.repository import Atspi
    except Exception:
        return []
    keep = {Atspi.Role.PUSH_BUTTON, Atspi.Role.TOGGLE_BUTTON, Atspi.Role.MENU_ITEM, Atspi.Role.ENTRY,
            Atspi.Role.CHECK_BOX, Atspi.Role.RADIO_BUTTON, Atspi.Role.LINK, Atspi.Role.PAGE_TAB,
            Atspi.Role.COMBO_BOX, Atspi.Role.TEXT, Atspi.Role.SLIDER}
    out = []
    def walk(n, depth=0):
        if depth > 25: return
        try:
            if n.get_role() in keep and n.get_state_set().contains(Atspi.StateType.SHOWING):
                e = n.get_component_iface().get_extents(Atspi.CoordType.SCREEN)
                if e.width > 3 and e.height > 3:
                    out.append(dict(box=(e.x, e.y, e.x + e.width, e.y + e.height), src="atspi", text=n.get_name() or ""))
            for i in range(n.get_child_count()): walk(n.get_child_at_index(i), depth + 1)
        except Exception: pass
    d = Atspi.get_desktop(0)
    for i in range(d.get_child_count()): walk(d.get_child_at_index(i))
    return out

def marks_cv(img):
    try: import cv2, numpy as np
    except ImportError: return []
    g = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2GRAY)
    e = cv2.dilate(cv2.Canny(g, 40, 120), np.ones((3, 3), np.uint8))
    cs, _ = cv2.findContours(e, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    out = []
    for c in cs:
        x, y, w, h = cv2.boundingRect(c)
        if 14 <= w <= 700 and 14 <= h <= 200: out.append(dict(box=(x, y, x + w, y + h), src="cv", text=""))
    return out

def iou(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0])); iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    i = ix * iy; u = (a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - i
    return i / u if u else 0

def gather(img, limit=120):
    ms = marks_atspi() + marks_ocr(img) + marks_cv(img)
    kept = []
    for m in ms:   # drop near-duplicates; earlier (more reliable) sources win
        if all(iou(m["box"], k["box"]) < 0.6 for k in kept): kept.append(m)
    return kept[:limit]

# ---------- rendering ----------
def _png(img):
    b = io.BytesIO(); img.save(b, "PNG"); return b.getvalue()

def render(img, marks, scale):
    im = img.resize((int(img.width * scale), int(img.height * scale)), Image.LANCZOS); d = ImageDraw.Draw(im)
    font = ImageFont.load_default(size=15)
    cols = ["#ff2d55", "#0a84ff", "#30d158", "#ff9f0a", "#bf5af2"]
    for i, m in enumerate(marks, 1):
        x0, y0, x1, y1 = [v * scale for v in m["box"]]; c = cols[i % 5]
        d.rectangle((x0, y0, x1, y1), outline=c, width=2)
        t = str(i); tw = d.textlength(t, font=font)
        d.rectangle((x0, y0 - 17, x0 + tw + 6, y0), fill=c); d.text((x0 + 3, y0 - 17), t, fill="white", font=font)
    return im

# ---------- model ----------
def client():
    import anthropic
    cfg = tomllib.loads((Path.home() / ".config/companion/ai.toml").read_text())
    return anthropic.Anthropic(api_key=cfg["api_key"])

def ask(cl, model, im, prompt):
    r = cl.messages.create(model=model, max_tokens=3000, messages=[{"role": "user", "content": [
        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": base64.b64encode(_png(im)).decode()}},
        {"type": "text", "text": prompt}]}])
    return next(b.text for b in r.content if b.type == "text"), r.usage

def ask_mark(cl, model, im, marks, q):
    t, u = ask(cl, model, im, f'The screenshot has numbered boxes over UI elements. Task: point the user to: {q}\n'
        'Reply with JSON only: {"mark": <box number or null if the target has no box or is not visible>}.')
    return json.loads(t[t.index("{"):t.rindex("}") + 1]).get("mark"), u

def ask_raw(cl, model, im, q, scale):
    t, u = ask(cl, model, im, f'This screenshot is {im.width}x{im.height} px. Point the user to: {q}\n'
        'Reply with JSON only: {"x": <pixel x>, "y": <pixel y>} of the centre of the target, or {"x": null, "y": null} if not visible.')
    j = json.loads(t[t.index("{"):t.rindex("}") + 1])
    return (None if j.get("x") is None else (j["x"] / scale, j["y"] / scale)), u
