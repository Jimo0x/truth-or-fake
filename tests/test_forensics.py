import io, sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import numpy as np
from PIL import Image, PngImagePlugin
from app import app
from forensics import analyze

def natural(seed=0):
    rng = np.random.default_rng(seed); base = np.linspace(30, 200, 640)[None, :, None].repeat(400, 0).repeat(3, 2)
    return np.clip(base + rng.normal(0, 9, base.shape), 0, 255).astype(np.uint8)

def to_bytes(arr, fmt="JPEG", **kw):
    b = io.BytesIO(); Image.fromarray(arr).save(b, fmt, **kw); return b.getvalue()

def test_ai_prompt_png_is_flagged():
    info = PngImagePlugin.PngInfo(); info.add_text("parameters", "a cat, Negative prompt: blurry, Steps: 30, Sampler: Euler, CFG scale: 7")
    r = analyze(to_bytes(natural(), "PNG", pnginfo=info))
    assert r["score"] >= 60 and any(s["id"] == "prompt" for s in r["signals"])

def test_copy_move_detected():
    a = natural(1); rng = np.random.default_rng(5); a[50:200, 40:200] = rng.integers(0, 255, (150, 160, 3)); a[220:370, 420:580] = a[50:200, 40:200]
    r = analyze(to_bytes(a, quality=95)); assert r["metrics"]["copy_move_pairs"] >= 8

def test_layers_and_api():
    c = app.test_client(); r = c.post("/api/analyze", data={"image": (io.BytesIO(to_bytes(natural())), "x.jpg")})
    assert r.status_code == 200 and set(r.json["layers"]) == {"ela", "noise", "spectrum", "copymove"}
    assert c.post("/api/analyze", data={"image": (io.BytesIO(b"xx"), "x.jpg")}).status_code == 400
