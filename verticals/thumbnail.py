"""Thumbnail generation — Leonardo or Gemini (16:9) + Pillow text overlay."""

import base64
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont

from .config import get_gemini_key
from .log import log
from .niche import get_visual_negative_prompt, load_niche
from .retry import with_retry

THUMB_WIDTH = 1280
THUMB_HEIGHT = 720

# Leonardo generates at 16:9 and _overlay_title upscales to THUMB_*. Mirrors
# the 576x1024 broll.py uses for portrait.
LEO_WIDTH = 1024
LEO_HEIGHT = 576


@with_retry(max_retries=3, base_delay=2.0)
def _generate_thumb_image(prompt: str, output_path: Path, api_key: str):
    """Generate a 16:9 thumbnail via Gemini native image generation."""
    url = (
        "https://generativelanguage.googleapis.com/v1beta"
        "/models/gemini-2.5-flash-image:generateContent"
    )
    body = {
        "contents": [{"parts": [{"text": f"Generate a 16:9 landscape image: {prompt}"}]}],
        "generationConfig": {"responseModalities": ["IMAGE", "TEXT"]},
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
        raise RuntimeError(f"Gemini API {r.status_code}: {detail}")

    data = r.json()
    for part in data.get("candidates", [{}])[0].get("content", {}).get("parts", []):
        if "inlineData" in part:
            img_b64 = part["inlineData"]["data"]
            output_path.write_bytes(base64.b64decode(img_b64))
            return
    raise RuntimeError("No image in Gemini response")


def _overlay_title(image_path: Path, title: str, output_path: Path):
    """Overlay bold title text with drop shadow on the thumbnail."""
    img = Image.open(image_path).convert("RGB")
    img = img.resize((THUMB_WIDTH, THUMB_HEIGHT), Image.LANCZOS)
    draw = ImageDraw.Draw(img)

    # Try to find a bold font, fall back to default.
    #
    # The candidate list was macOS + Linux only, so on Windows every truetype
    # lookup failed and this fell through to load_default() — a fixed-size
    # bitmap font that silently ignores font_size. The result was a 1280x720
    # thumbnail with a ~10px title on it, technically present and completely
    # unreadable. Windows faces are listed first because that is where the
    # scheduled job actually runs.
    font_size = 64
    font = None
    for font_name in [
        "arialbd.ttf",                      # Windows, bold
        "segoeuib.ttf",                     # Windows, bold
        "arial.ttf",                        # Windows, regular
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/SFNSDisplay.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]:
        try:
            font = ImageFont.truetype(font_name, font_size)
            break
        except OSError:
            continue
    if font is None:
        # Pillow >= 10.1 can scale the built-in font; older versions cannot,
        # in which case a small title still beats crashing the upload.
        try:
            font = ImageFont.load_default(size=font_size)
        except TypeError:
            font = ImageFont.load_default()

    # Word wrap the title
    max_width = THUMB_WIDTH - 80  # 40px padding each side
    lines = _wrap_text(draw, title, font, max_width)
    text_block = "\n".join(lines)

    # Calculate position (center, lower third)
    bbox = draw.multiline_textbbox((0, 0), text_block, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    x = (THUMB_WIDTH - text_w) // 2
    y = THUMB_HEIGHT - text_h - 60  # 60px from bottom

    # Drop shadow
    shadow_offset = 3
    draw.multiline_text(
        (x + shadow_offset, y + shadow_offset),
        text_block, fill=(0, 0, 0), font=font, align="center",
    )

    # Main text
    draw.multiline_text(
        (x, y), text_block, fill=(255, 255, 255), font=font, align="center",
    )

    img.save(output_path)


def _wrap_text(draw: ImageDraw.Draw, text: str, font, max_width: int) -> list[str]:
    """Simple word-wrap for Pillow text rendering."""
    words = text.split()
    lines = []
    current = ""
    for word in words:
        test = f"{current} {word}".strip()
        bbox = draw.textbbox((0, 0), test, font=font)
        if bbox[2] - bbox[0] <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _fallback_thumb(out_path: Path, profile: dict):
    """Flat brand-coloured backdrop for when every generator is unavailable.

    The title overlay still goes on top, so this is a plain but legitimate
    thumbnail — better than letting the upload ship with whatever frame
    YouTube picks out of the video.
    """
    palette = (profile.get("visuals", {}) or {}).get("color_palette") or ["#1D3A53"]
    hex_colour = str(palette[0]).lstrip("#")
    try:
        rgb = tuple(int(hex_colour[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        rgb = (29, 58, 83)
    Image.new("RGB", (THUMB_WIDTH, THUMB_HEIGHT), rgb).save(out_path)


def generate_thumbnail(draft: dict, out_dir: Path, niche: str | None = None) -> Path:
    """Generate a YouTube thumbnail, then overlay the video title.

    Provider selection mirrors broll.py: Leonardo when the niche declares
    `visuals.leonardo.provider: leonardo` and a key is set, otherwise Gemini,
    otherwise a flat brand-coloured backdrop.

    This used to be Gemini-only, which meant it never worked: Gemini's image
    model has zero free-tier allocation, so every call 429'd through four
    retries and cmd_upload shipped the video with no thumbnail at all.

    Returns path to the final thumbnail PNG.
    """
    niche = niche or draft.get("niche", "general")
    profile = load_niche(niche)
    prompt = draft.get("thumbnail_prompt", "Cinematic YouTube thumbnail")
    title = draft.get("youtube_title", draft.get("news", ""))
    job_id = draft.get("job_id", "unknown")

    raw_path = out_dir / f"thumb_raw_{job_id}.png"
    final_path = out_dir / f"thumb_{job_id}.png"

    leo_config = (profile.get("visuals", {}) or {}).get("leonardo", {}) or {}
    # The title is burned on by Pillow afterwards, so any lettering the model
    # invents would collide with it. Suppress it the same way b-roll does.
    negative_prompt = get_visual_negative_prompt(profile)
    generated = False

    if leo_config.get("provider") == "leonardo":
        try:
            from .leonardo import generate_image_leonardo, get_leonardo_key
            api_key = get_leonardo_key()
            if api_key:
                log("Generating thumbnail via Leonardo.ai...")
                generate_image_leonardo(
                    prompt=prompt,
                    output_path=raw_path,
                    api_key=api_key,
                    model_id=leo_config.get("model_id", "de7d3faf-762f-48e0-b3b7-9d0ac3a3fcf3"),
                    contrast=leo_config.get("contrast", 3.5),
                    width=LEO_WIDTH,
                    height=LEO_HEIGHT,
                    negative_prompt=negative_prompt,
                )
                generated = True
        except Exception as e:
            log(f"Leonardo thumbnail failed: {e} — falling back to Gemini")

    if not generated:
        try:
            log("Generating thumbnail via Gemini Imagen...")
            _generate_thumb_image(prompt, raw_path, get_gemini_key())
            generated = True
        except Exception as e:
            log(f"Gemini thumbnail failed: {e} — using flat backdrop")

    if not generated:
        _fallback_thumb(raw_path, profile)

    log("Adding title overlay...")
    _overlay_title(raw_path, title, final_path)

    log(f"Thumbnail saved: {final_path.name}")
    return final_path
