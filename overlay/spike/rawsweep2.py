"""Harder scene (Vivaldi: tiny toolbar icons, web page). Ground truth read off the image by hand (+-5 px)."""
import sys, time
sys.path.insert(0, ".")
import som
from PIL import Image
CASES = [
 ("the browser's Back arrow button", (91,77,111,95)),
 ("the browser's Reload button", (160,77,178,95)),
 ("the '+' new-tab button in the tab strip", (628,42,649,63)),
 ("the Download icon in the browser toolbar (top right area)", (2158,76,2179,96)),
 ("the 'Follow on X' button on the web page", (710,196,853,232)),
 ("the 'Star on GitHub' button on the web page", (865,196,1051,232)),
 ("the 'Watchlist' link in the page's navigation bar", (1033,125,1096,143)),
 ("the 'Toolkit' link in the page's navigation bar", (1123,125,1169,143)),
 ("the light/dark theme toggle (sun icon) in the page header", (1853,119,1885,151)),
 ("the 'EN' language button in the page header", (1774,119,1834,151)),
 ("the 'Boot GTA VI' stat tile", (1600,911,1720,991)),
 ("the window minimise button at the top right of the browser", (2449,37,2467,55)),
]
PAD = 14
S = sys.argv[1]; img = Image.open(f"{S}/full2.png").convert("RGB"); cl = som.client()
for model, scale in (("claude-haiku-5-5", 0.75), ("claude-haiku-5-5", 1.0), ("claude-sonnet-5-5", 0.75), ("claude-sonnet-5-5", 1.0), ("claude-opus-5-5", 1.0)):
    im = img.resize((int(img.width*scale), int(img.height*scale))); hits = 0; errs = []; t0 = time.time()
    for q, gt in CASES:
        try: p, _ = som.ask_raw(cl, model, im, q, scale)
        except Exception: p = None
        if p is None: errs.append(None); continue
        errs.append(round(((p[0]-(gt[0]+gt[2])/2)**2 + (p[1]-(gt[1]+gt[3])/2)**2) ** .5))
        hits += gt[0]-PAD <= p[0] <= gt[2]+PAD and gt[1]-PAD <= p[1] <= gt[3]+PAD
    print(f"{model:18} {int(img.width*scale)}px  {hits}/{len(CASES)}  {(time.time()-t0)/len(CASES):.1f}s/query  errs {errs}", flush=True)
