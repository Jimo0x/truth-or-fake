"""Truth or Fake — moteur d'analyse forensique d'image.

Chaque analyse renvoie des indices (« signals ») pondérés. Aucun indice
n'est une preuve à lui seul : le score final est une estimation.
"""
from __future__ import annotations

import base64
import io
import re

import cv2
import numpy as np
from PIL import ExifTags, Image, ImageChops, ImageEnhance

AI_MARKERS = ["stable diffusion", "midjourney", "dall-e", "dall·e", "firefly", "novelai", "comfyui", "automatic1111",
              "invokeai", "leonardo", "imagen", "flux", "sdxl", "dreamstudio", "bing image creator", "openai"]
EDITORS = ["photoshop", "gimp", "lightroom", "affinity", "pixelmator", "snapseed", "picsart", "canva", "facetune",
           "paint.net", "krita", "capture one", "luminar"]


def _png_b64(arr: np.ndarray) -> str:
    ok, buf = cv2.imencode(".png", arr)
    return "data:image/png;base64," + base64.b64encode(buf.tobytes()).decode()


def _heat(gray: np.ndarray) -> np.ndarray:
    g = cv2.normalize(gray.astype(np.float32), None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    lut = np.zeros((256, 1, 3), np.uint8)  # palette noir → rouge → blanc
    for i in range(256):
        lut[i, 0] = (max(0, i * 2 - 255), max(0, i * 2 - 255), min(255, i * 2))
    return cv2.LUT(cv2.cvtColor(g, cv2.COLOR_GRAY2BGR), lut)


def metadata(img: Image.Image, raw: bytes) -> tuple[dict, list]:
    meta, sig = {"format": img.format, "taille": f"{img.width}×{img.height}", "mode": img.mode}, []
    exif = {}
    try:
        for k, v in (img.getexif() or {}).items():
            name = ExifTags.TAGS.get(k, str(k))
            if isinstance(v, bytes):
                continue
            exif[name] = str(v)[:120]
        sub = img.getexif().get_ifd(0x8769)
        for k, v in sub.items():
            name = ExifTags.TAGS.get(k, str(k))
            if not isinstance(v, bytes):
                exif[name] = str(v)[:120]
    except Exception:
        pass
    meta["exif"] = exif
    text_chunks = {k: str(v)[:400] for k, v in (img.info or {}).items() if isinstance(v, (str, bytes)) and k not in ("icc_profile", "exif")}
    meta["chunks"] = {k: (v if isinstance(v, str) else "<binaire>") for k, v in text_chunks.items()}

    blob = " ".join([*exif.values(), *map(str, text_chunks.values())]).lower()
    low_raw = raw[:200000].lower()
    for m in AI_MARKERS:
        if m in blob or m.encode() in low_raw:
            sig.append({"id": "ai_meta", "w": 45, "level": "fake", "msg": f"Signature d'un générateur d'IA trouvée dans les métadonnées : « {m} »."})
            break
    if "parameters" in text_chunks or re.search(r"(negative prompt|cfg scale|sampler)", blob):
        sig.append({"id": "prompt", "w": 40, "level": "fake", "msg": "Un prompt de génération est intégré au fichier (bloc « parameters »)."})
    if b"c2pa" in low_raw or b"jumb" in low_raw:
        sig.append({"id": "c2pa", "w": 10, "level": "info", "msg": "Manifeste C2PA / Content Credentials présent : l'historique de création est déclaré."})
    soft = exif.get("Software", "").lower()
    for e in EDITORS:
        if e in soft:
            sig.append({"id": "editor", "w": 18, "level": "warn", "msg": f"Logiciel de retouche déclaré : {exif['Software']}."})
            break
    if img.format == "JPEG":
        if not exif:
            sig.append({"id": "noexif", "w": 8, "level": "warn", "msg": "JPEG sans aucune donnée EXIF : métadonnées supprimées (réseaux sociaux, export, génération)."})
        elif exif.get("Make") or exif.get("Model"):
            sig.append({"id": "camera", "w": -15, "level": "ok", "msg": f"Appareil déclaré : {exif.get('Make', '')} {exif.get('Model', '')}".strip() + "."})
        if exif.get("DateTimeOriginal") and exif.get("DateTime") and exif["DateTimeOriginal"] != exif["DateTime"]:
            sig.append({"id": "dates", "w": 10, "level": "warn", "msg": f"Date de prise ({exif['DateTimeOriginal']}) ≠ date de modification ({exif['DateTime']})."})
    if img.format == "PNG" and max(img.size) >= 512 and img.width % 64 == 0 and img.height % 64 == 0 and not exif:
        sig.append({"id": "dims", "w": 10, "level": "warn", "msg": f"PNG sans EXIF aux dimensions multiples de 64 ({img.width}×{img.height}), typiques des modèles de diffusion."})
    return meta, sig


def jpeg_quality(img: Image.Image) -> int | None:
    q = getattr(img, "quantization", None)
    if not q:
        return None
    t = np.array(q[0][:64], dtype=float)
    std = np.array([16, 11, 10, 16, 24, 40, 51, 61, 12, 12, 14, 19, 26, 58, 60, 55, 14, 13, 16, 24, 40, 57, 69, 56, 14, 17, 22, 29, 51,
                    87, 80, 62, 18, 22, 37, 56, 68, 109, 103, 77, 24, 35, 55, 64, 81, 104, 113, 92, 49, 64, 78, 87, 103, 121, 120, 101,
                    72, 92, 95, 98, 112, 100, 103, 99], dtype=float)
    s = float(np.mean(t / std) * 100)
    return int(round(100 - s / 2 if s <= 100 else 5000 / s))


def ela(img: Image.Image, quality: int = 90) -> tuple[np.ndarray, float, float]:
    rgb = img.convert("RGB")
    buf = io.BytesIO()
    rgb.save(buf, "JPEG", quality=quality)
    diff = ImageChops.difference(rgb, Image.open(io.BytesIO(buf.getvalue())))
    arr = np.asarray(diff).astype(np.float32).max(axis=2)
    scale = 255.0 / max(arr.max(), 1)
    vis = np.asarray(ImageEnhance.Brightness(diff).enhance(scale))[:, :, ::-1]
    # hétérogénéité : écart entre les blocs les plus « chauds » et la médiane
    h, w = arr.shape
    b = 16
    blocks = arr[: h // b * b, : w // b * b].reshape(h // b, b, w // b, b).mean(axis=(1, 3))
    med = float(np.median(blocks)) + 1e-6
    hot = float(np.percentile(blocks, 99.5))
    return vis, hot / med, float(arr.mean())


def noise_map(gray: np.ndarray) -> tuple[np.ndarray, float]:
    resid = gray.astype(np.float32) - cv2.medianBlur(gray, 3).astype(np.float32)
    b = 24
    h, w = resid.shape
    hh, ww = h // b, w // b
    if hh < 2 or ww < 2:
        return _heat(np.abs(resid)), 0.0
    v = resid[: hh * b, : ww * b].reshape(hh, b, ww, b).std(axis=(1, 3))
    cv_ = float(v.std() / (v.mean() + 1e-6))
    return _heat(cv2.resize(v, (w, h), interpolation=cv2.INTER_NEAREST)), cv_


def spectrum(gray: np.ndarray) -> tuple[np.ndarray, float]:
    g = cv2.resize(gray, (512, 512)).astype(np.float32)
    f = np.fft.fftshift(np.fft.fft2(g - g.mean()))
    mag = np.log1p(np.abs(f))
    # pics périodiques hors centre : indice d'artefacts de suréchantillonnage (GAN / diffusion)
    m = mag.copy()
    c = 256
    m[c - 20:c + 20, c - 20:c + 20] = 0
    m[c - 2:c + 3, :] = 0
    m[:, c - 2:c + 3] = 0
    peaks = float((m > m.mean() + 6 * m.std()).sum())
    return _heat(mag), peaks


def copy_move(gray: np.ndarray, color: np.ndarray) -> tuple[np.ndarray, int]:
    orb = cv2.ORB_create(3000)
    kp, des = orb.detectAndCompute(gray, None)
    vis = color.copy()
    if des is None or len(kp) < 10:
        return vis, 0
    bf = cv2.BFMatcher(cv2.NORM_HAMMING)
    pairs = 0
    minsep = max(gray.shape) * 0.05
    for m in bf.knnMatch(des, des, k=3):
        for n in m[1:]:  # m[0] est le point lui-même
            if n.distance < 28:
                p1, p2 = np.array(kp[n.queryIdx].pt), np.array(kp[n.trainIdx].pt)
                if np.linalg.norm(p1 - p2) > minsep:
                    pairs += 1
                    cv2.line(vis, tuple(map(int, p1)), tuple(map(int, p2)), (47, 23, 229), 1, cv2.LINE_AA)
                    cv2.circle(vis, tuple(map(int, p1)), 3, (82, 59, 255), -1)
                break
    return vis, pairs // 2


def analyze(raw: bytes) -> dict:
    img = Image.open(io.BytesIO(raw))
    img.load()
    meta, signals = metadata(img, raw)
    rgb = np.asarray(img.convert("RGB"))[:, :, ::-1].copy()
    k = 1600 / max(rgb.shape[:2])
    if k < 1:
        rgb = cv2.resize(rgb, None, fx=k, fy=k, interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(rgb, cv2.COLOR_BGR2GRAY)

    q = jpeg_quality(img)
    if q is not None:
        meta["qualité JPEG estimée"] = q

    ela_vis, ela_ratio, ela_mean = ela(Image.fromarray(rgb[:, :, ::-1]))
    if ela_ratio > 9 and ela_mean > 0.4:
        signals.append({"id": "ela", "w": 22, "level": "fake", "msg": f"ELA : certaines zones se recompressent très différemment du reste (ratio {ela_ratio:.1f}). Possible collage ou retouche locale."})
    elif ela_ratio > 5.5:
        signals.append({"id": "ela", "w": 10, "level": "warn", "msg": f"ELA : hétérogénéité modérée (ratio {ela_ratio:.1f}). À vérifier visuellement sur la couche ELA."})
    else:
        signals.append({"id": "ela", "w": -8, "level": "ok", "msg": f"ELA homogène (ratio {ela_ratio:.1f}) : pas de zone recompressée isolée."})

    nz_vis, nz_cv = noise_map(gray)
    if nz_cv < 0.18 and gray.std() > 20:
        signals.append({"id": "noise", "w": 18, "level": "warn", "msg": "Bruit capteur anormalement uniforme : fréquent sur les images générées ou très lissées."})
    elif nz_cv > 1.1:
        signals.append({"id": "noise", "w": 12, "level": "warn", "msg": "Le bruit varie fortement d'une zone à l'autre : des régions peuvent provenir de sources différentes."})

    sp_vis, peaks = spectrum(gray)
    if peaks > 40:
        signals.append({"id": "fft", "w": 15, "level": "warn", "msg": f"Spectre : {int(peaks)} pics périodiques, signature possible d'un suréchantillonnage (GAN / diffusion) ou d'une trame."})

    cm_vis, pairs = copy_move(gray, rgb)
    if pairs >= 25:
        signals.append({"id": "copymove", "w": 25, "level": "fake", "msg": f"Copier-coller interne : {pairs} paires de points identiques éloignées. Une zone semble dupliquée."})
    elif pairs >= 8:
        signals.append({"id": "copymove", "w": 8, "level": "warn", "msg": f"{pairs} correspondances internes (motifs répétitifs ou duplication partielle)."})

    score = int(max(0, min(100, 25 + sum(s["w"] for s in signals))))
    verdict = "Probablement authentique" if score < 35 else "Suspect" if score < 60 else "Probablement manipulée / générée"
    return {
        "score": score, "verdict": verdict, "signals": sorted(signals, key=lambda s: -s["w"]), "meta": meta,
        "layers": {"ela": _png_b64(ela_vis), "noise": _png_b64(nz_vis), "spectrum": _png_b64(sp_vis), "copymove": _png_b64(cm_vis)},
        "metrics": {"ela_ratio": round(ela_ratio, 2), "noise_cv": round(nz_cv, 3), "fft_peaks": int(peaks), "copy_move_pairs": pairs},
    }
