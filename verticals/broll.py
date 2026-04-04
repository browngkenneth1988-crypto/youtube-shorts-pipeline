"""B-roll generation + Ken Burns animation.

Supports multiple image providers:
- Gemini Imagen (default, free tier)
- Leonardo.ai (reference-image-aware, keeps character consistent)
"""

import base64
import textwrap
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont

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


def burn_quote_on_frame(img_path: Path, quote: str, position: str = "center"):
    """Burn an inspirational quote as visible text onto a b-roll frame.

    Adds a semi-transparent dark overlay behind the text for readability,
    then renders the quote in a warm, gentle font style.
    """
    img = Image.open(img_path).convert("RGBA")
    w, h = img.size

    # Create overlay for text background
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    # Try to load a nice font, fall back to default
    font_size = w // 14  # Responsive to image width
    try:
        font = ImageFont.truetype("arial.ttf", font_size)
    except OSError:
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size)
        except OSError:
            font = ImageFont.load_default()

    # Wrap text to fit image width (with padding)
    max_chars = max(15, w // (font_size // 2))
    lines = textwrap.wrap(quote, width=max_chars)
    text_block = "\n".join(lines)

    # Calculate text dimensions
    bbox = draw.multiline_textbbox((0, 0), text_block, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    # Position the text
    padding = 40
    if position == "top":
        text_y = padding * 4
    elif position == "lower_third":
        text_y = h - text_h - padding * 3
    else:
        text_y = (h - text_h) // 2

    text_x = (w - text_w) // 2

    # Draw semi-transparent dark rectangle behind text
    rect_margin = 30
    draw.rounded_rectangle(
        [
            text_x - rect_margin,
            text_y - rect_margin,
            text_x + text_w + rect_margin,
            text_y + text_h + rect_margin,
        ],
        radius=20,
        fill=(0, 0, 0, 140),
    )

    # Draw the quote text in warm white/gold
    draw.multiline_text(
        (text_x, text_y),
        text_block,
        font=font,
        fill=(255, 248, 240, 255),  # Warm white
        align="center",
    )

    # Composite overlay onto image
    result = Image.alpha_composite(img, overlay).convert("RGB")
    result.save(img_path)
    log(f"Quote burned onto {img_path.name}")


def _get_reference_images(niche_name: str) -> list[Path]:
    """Get all available reference images for a niche's character."""
    profile = load_niche(niche_name)
    character = profile.get("character", {})
    ref_images = character.get("reference_images", [])
    project_root = NICHES_DIR.parent

    found = []
    for ref_path in ref_images:
        full_path = project_root / ref_path
        if full_path.exists():
            found.append(full_path)
    return found


def generate_broll(prompts: list, out_dir: Path, niche: str = "general") -> list[Path]:
    """Generate 3 b-roll frames, with provider selection based on niche.

    If the niche has Leonardo.ai config and reference images, uses
    Leonardo for character-consistent generation. Falls back to Gemini.
    """
    profile = load_niche(niche)
    leo_config = profile.get("visuals", {}).get("leonardo", {})
    use_leonardo = leo_config.get("provider") == "leonardo"
    ref_images = _get_reference_images(niche) if use_leonardo else []

    frames = []

    for i, prompt in enumerate(prompts[:3]):
        out_path = out_dir / f"broll_{i}.png"

        # Pick reference image — alternate between available refs for variety
        reference_image = ref_images[i % len(ref_images)] if ref_images else None

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
