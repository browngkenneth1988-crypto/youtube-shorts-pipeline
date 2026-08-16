"""Leonardo.ai image generation with reference image support.

Uses image-to-image (img2img) to maintain visual consistency of Otto
across all generated b-roll frames. The reference images of Otto are
sent as init images so every frame features the same recognizable dog.
"""

import time
from pathlib import Path

import requests

from .config import _get_key
from .log import log
from .retry import with_retry

LEONARDO_API_BASE = "https://cloud.leonardo.ai/api/rest/v1"


def get_leonardo_key() -> str:
    return _get_key("LEONARDO_API_KEY")


def _headers(api_key: str) -> dict:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


@with_retry(max_retries=3, base_delay=3.0)
def _upload_init_image(image_path: Path, api_key: str) -> str:
    """Upload a reference image to Leonardo and return the image ID."""
    # Step 1: Get presigned URL
    ext = image_path.suffix.lstrip(".")
    r = requests.post(
        f"{LEONARDO_API_BASE}/init-image",
        json={"extension": ext},
        headers=_headers(api_key),
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    upload_url = data["uploadInitImage"]["url"]
    image_id = data["uploadInitImage"]["id"]
    fields_raw = data["uploadInitImage"].get("fields", "")

    # Step 2: Upload to presigned URL
    if isinstance(fields_raw, str):
        import json as _json
        fields = _json.loads(fields_raw) if fields_raw else {}
    else:
        fields = fields_raw

    with open(image_path, "rb") as f:
        files = {"file": (image_path.name, f)}
        r2 = requests.post(upload_url, data=fields, files=files, timeout=60)
        r2.raise_for_status()

    return image_id


@with_retry(max_retries=3, base_delay=5.0)
def generate_image_leonardo(
    prompt: str,
    output_path: Path,
    api_key: str,
    reference_image_path: Path | None = None,
    model_id: str = "de7d3faf-762f-48e0-b3b7-9d0ac3a3fcf3",  # Leonardo Phoenix 1.0
    contrast: float = 3.5,
    init_strength: float = 0.35,
    width: int = 576,
    height: int = 1024,
    negative_prompt: str = "",
) -> None:
    """Generate an image via Leonardo.ai API.

    If reference_image_path is provided, uses image-to-image mode
    to maintain visual consistency with the reference (Otto).

    negative_prompt is the API's own exclusion field. Putting "no text, no
    lettering" in the positive prompt does not work — image models do not
    reliably parse negation, and a real run rendered a diagram covered in
    misspelled pseudo-words with exactly that wording in the prompt.
    """
    headers = _headers(api_key)

    body = {
        "prompt": prompt,
        "modelId": model_id,
        "width": width,
        "height": height,
        "contrast": contrast,
        "num_images": 1,
        "alchemy": True,
    }
    if negative_prompt:
        body["negative_prompt"] = negative_prompt

    # Upload reference image for img2img if provided
    if reference_image_path and reference_image_path.exists():
        init_image_id = _upload_init_image(reference_image_path, api_key)
        body["init_image_id"] = init_image_id
        body["init_strength"] = init_strength
        log(f"Using reference image: {reference_image_path.name}")

    # Start generation
    r = requests.post(
        f"{LEONARDO_API_BASE}/generations",
        json=body,
        headers=headers,
        timeout=30,
    )
    r.raise_for_status()
    generation_id = r.json()["sdGenerationJob"]["generationId"]
    log(f"Leonardo generation started: {generation_id}")

    # Poll for completion (max 120 seconds)
    for _ in range(24):
        time.sleep(5)
        r = requests.get(
            f"{LEONARDO_API_BASE}/generations/{generation_id}",
            headers=headers,
            timeout=15,
        )
        r.raise_for_status()
        gen_data = r.json()["generations_by_pk"]
        status = gen_data.get("status")

        if status == "COMPLETE":
            images = gen_data.get("generated_images", [])
            if not images:
                raise RuntimeError("Leonardo generation complete but no images returned")
            image_url = images[0]["url"]
            img_r = requests.get(image_url, timeout=30)
            img_r.raise_for_status()
            output_path.write_bytes(img_r.content)
            log(f"Leonardo image saved: {output_path}")
            return
        elif status == "FAILED":
            raise RuntimeError(f"Leonardo generation failed: {gen_data}")

    raise RuntimeError("Leonardo generation timed out after 120 seconds")
