"""B-roll generation + Ken Burns animation.

Supports multiple image providers:
- Gemini Imagen (default, free tier)
- Leonardo.ai (reference-image-aware, keeps character consistent)
"""

import base64
from pathlib import Path

import requests
from PIL import Image

from .config import VIDEO_WIDTH, VIDEO_HEIGHT, get_gemini_key, run_cmd
from .log import log
from .niche import load_niche, NICHES_DIR
from .retry import with_retry


@with_retry(max_retries=3, base_delay=2.0)
def _generate_image_gemini(prompt: str, output_path: Path, api_key: str):
    """Generate image via Gemini's image generation capability."""
    url = (
        "https://generativelanguage.googleapis.com/v1beta"
        "/models/gemini-2.5-flash-image:generateContent"
    )
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseModalities": ["TEXT", "IMAGE"],
        },
    }
    r = requests.post(
        url, json=body, timeout=90,
        headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
    )
    if r.status_code != 200:
        try:
            detail = r.json().get("error", {}).get("message", r.text[:200])
        except Exception:
            detail = r.text[:200]
        raise RuntimeError(f"Gemini Image API {r.status_code}: {detail}")
    data = r.json()
    # Extract image from response parts
    for candidate in data.get("candidates", []):
        for part in candidate.get("content", {}).get("parts", []):
            if "inlineData" in part:
                img_b64 = part["inlineData"]["data"]
                output_path.write_bytes(base64.b64decode(img_b64))
                return
    raise RuntimeError("No image in Gemini response")


def _fallback_frame(i: int, out_dir: Path) -> Path:
    """Solid colour fallback frame if Gemini fails."""
    colors = [(20, 20, 60), (40, 10, 40), (10, 30, 50)]
    img = Image.new("RGB", (VIDEO_WIDTH, VIDEO_HEIGHT), colors[i % len(colors)])
    path = out_dir / f"broll_{i}.png"
    img.save(path)
    return path


def _resize_to_portrait(out_path: Path):
    """Resize/crop image to 9:16 portrait format."""
    img = Image.open(out_path).convert("RGB")
    target_w, target_h = VIDEO_WIDTH, VIDEO_HEIGHT
    orig_w, orig_h = img.size
    scale = max(target_w / orig_w, target_h / orig_h)
    new_w, new_h = int(orig_w * scale), int(orig_h * scale)
    img = img.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - target_w) // 2
    top = (new_h - target_h) // 2
    img = img.crop((left, top, left + target_w, top + target_h))
    img.save(out_path)


def _get_reference_image(niche_name: str) -> Path | None:
    """Get the first available reference image for a niche's character."""
    profile = load_niche(niche_name)
    character = profile.get("character", {})
    ref_images = character.get("reference_images", [])
    project_root = NICHES_DIR.parent

    for ref_path in ref_images:
        full_path = project_root / ref_path
        if full_path.exists():
            return full_path
    return None


def generate_broll(prompts: list, out_dir: Path, niche: str = "general") -> list[Path]:
    """Generate 3 b-roll frames, with provider selection based on niche.

    If the niche has Leonardo.ai config and reference images, uses
    Leonardo for character-consistent generation. Falls back to Gemini.
    """
    profile = load_niche(niche)
    leo_config = profile.get("visuals", {}).get("leonardo", {})
    use_leonardo = leo_config.get("provider") == "leonardo"
    reference_image = _get_reference_image(niche) if use_leonardo else None

    frames = []

    for i, prompt in enumerate(prompts[:3]):
        out_path = out_dir / f"broll_{i}.png"

        # Try Leonardo.ai first if configured (with or without reference images)
        if use_leonardo:
            try:
                from .leonardo import generate_image_leonardo, get_leonardo_key
                api_key = get_leonardo_key()
                if api_key:
                    ref_label = reference_image.name if reference_image else "none"
                    log(f"Generating b-roll frame {i+1}/3 via Leonardo.ai (ref: {ref_label})...")
                    generate_image_leonardo(
                        prompt=prompt,
                        output_path=out_path,
                        api_key=api_key,
                        reference_image_path=reference_image,
                        model_id=leo_config.get("model_id", "de7d3faf-762f-48e0-b3b7-9d0ac3a3fcf3"),
                        contrast=leo_config.get("contrast", 3.5),
                        init_strength=leo_config.get("init_strength", 0.35),
                        width=576,
                        height=1024,
                    )
                    _resize_to_portrait(out_path)
                    frames.append(out_path)
                    continue
            except Exception as e:
                log(f"Leonardo frame {i+1} failed: {e} — falling back to Gemini")

        # Gemini Imagen fallback
        log(f"Generating b-roll frame {i+1}/3 via Gemini Imagen...")
        try:
            api_key = get_gemini_key()
            _generate_image_gemini(prompt, out_path, api_key)
            _resize_to_portrait(out_path)
            frames.append(out_path)
        except Exception as e:
            log(f"Frame {i+1} failed: {e} — using fallback")
            frames.append(_fallback_frame(i, out_dir))

    return frames


def animate_frame(img_path: Path, out_path: Path, duration: float, effect: str = "zoom_in"):
    """Ken Burns animation on a single frame."""
    fps = 30
    frames = int(duration * fps)
    w, h = VIDEO_WIDTH, VIDEO_HEIGHT

    if effect == "zoom_in":
        vf = (
            f"scale={int(w * 1.12)}:{int(h * 1.12)},"
            f"zoompan=z='1.12-0.12*on/{frames}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
            f":d={frames}:s={w}x{h}:fps={fps}"
        )
    elif effect == "pan_right":
        vf = (
            f"scale={int(w * 1.15)}:{int(h * 1.15)},"
            f"zoompan=z=1.15:x='0.15*iw*on/{frames}':y='ih*0.075'"
            f":d={frames}:s={w}x{h}:fps={fps}"
        )
    else:  # zoom_out
        vf = (
            f"scale={int(w * 1.12)}:{int(h * 1.12)},"
            f"zoompan=z='1.0+0.12*on/{frames}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
            f":d={frames}:s={w}x{h}:fps={fps}"
        )

    run_cmd([
        "ffmpeg", "-loop", "1", "-i", str(img_path),
        "-vf", vf, "-t", str(duration), "-r", str(fps),
        "-pix_fmt", "yuv420p", str(out_path), "-y", "-loglevel", "quiet",
    ])
