"""Image generation routed through the configured image_maker model role."""

from __future__ import annotations

import base64
import re
from pathlib import Path
from typing import Any

import httpx

from magent.config import Config
from magent.provider_cooldown import cooldown_from_exception, provider_cooldown_remaining
from magent.providers import _build_api_kwargs

VALID_ASPECT_RATIOS = {"landscape": "1536x1024", "portrait": "1024x1536", "square": "1024x1024"}


async def generate_image_with_role(
    config: Config,
    prompt: str,
    output_path: str | Path,
    *,
    aspect_ratio: str = "landscape",
    reference_image: str = "",
) -> dict[str, Any]:
    provider_id, model = config.provider_and_model_for_role("image_maker")
    if not config.model_for_role("image_maker"):
        return {"ok": False, "error": "image_maker role is not configured. Run `magent model image-wizard`."}
    remaining = provider_cooldown_remaining(provider_id)
    if remaining:
        return {"ok": False, "provider": provider_id, "error": f"provider cooldown active for {remaining:.0f}s"}
    try:
        image_bytes, source = await _generate_image(config, provider_id, model, prompt, aspect_ratio, reference_image)
    except Exception as exc:
        cooldown_from_exception(provider_id, exc)
        return {"ok": False, "provider": provider_id, "model": model, "error": str(exc)}

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(image_bytes)
    return {
        "ok": True,
        "path": str(path),
        "bytes": len(image_bytes),
        "provider": provider_id,
        "model": model,
        "source": source,
        "aspect_ratio": aspect_ratio if aspect_ratio in VALID_ASPECT_RATIOS else "landscape",
    }


async def _generate_image(
    config: Config,
    provider_id: str,
    model: str,
    prompt: str,
    aspect_ratio: str,
    reference_image: str,
) -> tuple[bytes, str]:
    import litellm

    litellm.suppress_debug_info = True
    provider_cfg = config.provider_config(provider_id)
    kwargs = _build_api_kwargs(provider_id, model, provider_cfg, config.resolve_api_key(provider_id))
    size = VALID_ASPECT_RATIOS.get(aspect_ratio, VALID_ASPECT_RATIOS["landscape"])
    request: dict[str, Any] = {
        **kwargs,
        "prompt": prompt,
        "size": size,
        "n": 1,
    }
    if reference_image:
        request["image"] = _image_arg(reference_image)
    response = await litellm.aimage_generation(**request)
    item = _first_image_item(response)
    if not item:
        raise RuntimeError("image provider returned no image")
    if item.get("b64_json"):
        return base64.b64decode(item["b64_json"]), "b64_json"
    url = item.get("url")
    if url:
        async with httpx.AsyncClient(timeout=120) as client:
            result = await client.get(url)
            result.raise_for_status()
            return result.content, "url"
    raise RuntimeError("image provider returned no b64_json or url")


def _first_image_item(response: Any) -> dict[str, Any] | None:
    data = getattr(response, "data", None)
    if data is None and isinstance(response, dict):
        data = response.get("data")
    if not data:
        return None
    item = data[0]
    if isinstance(item, dict):
        return item
    return {
        "url": getattr(item, "url", None),
        "b64_json": getattr(item, "b64_json", None),
    }


def _image_arg(reference_image: str) -> Any:
    if re.match(r"https?://", reference_image):
        return reference_image
    path = Path(reference_image).expanduser()
    data = path.read_bytes()
    mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"
