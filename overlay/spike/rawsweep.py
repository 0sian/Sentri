import sys, time, re
sys.path.insert(0, ".")
import som
from PIL import Image
src = open("eval.py").read()
CASES = eval(re.search(r"CASES = (\[.*?\n\])", src, re.S).group(1)); PAD = 14
S = sys.argv[1]; img = Image.open(f"{S}/full.png").convert("RGB"); cl = som.client()
for model in ("claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5"):
    for scale in (0.5, 0.75, 1.0):
        im = img.resize((int(img.width*scale), int(img.height*scale))); hits = 0; errs = []; t0 = time.time()
        for q, gt in CASES:
            try: p, _ = som.ask_raw(cl, model, im, q, scale)
            except Exception as e: p = None
            if p is None: errs.append(None); continue
            e = ((p[0]-(gt[0]+gt[2])/2)**2 + (p[1]-(gt[1]+gt[3])/2)**2) ** .5; errs.append(round(e))
            hits += gt[0]-PAD <= p[0] <= gt[2]+PAD and gt[1]-PAD <= p[1] <= gt[3]+PAD
        print(f"{model:18} {int(img.width*scale)}px  {hits}/10  {(time.time()-t0)/10:.1f}s/query  errs {errs}", flush=True)
