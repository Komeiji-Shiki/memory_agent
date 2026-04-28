"""
Image caption fallback for non-vision models.
"""

from __future__ import annotations

import copy
import logging
from typing import Any, Dict, List, Optional, Tuple

import httpx
from openai import OpenAI
import fnmatch


def _model_supports_images(model: str, route_config: Optional[Dict[str, Any]], config: Dict[str, Any]) -> bool:
    """
    判定模型是否原生支持图片，任一条件满足则视为支持：
    1) 路由配置 supports_images/vision 显式为 True
    2) vision_models 列表中匹配到（支持通配符，如 deepseek-*）
    """
    model_lower = (model or "").lower()

    if route_config:
        if "supports_images" in route_config:
            val = bool(route_config.get("supports_images"))
            logging.debug(f"[ImageFallback] supports_images via route_config for {model}: {val}")
            return val
        if "vision" in route_config:
            val = bool(route_config.get("vision"))
            logging.debug(f"[ImageFallback] vision via route_config for {model}: {val}")
            return val

    vision_models = config.get("vision_models", []) or []
    if isinstance(vision_models, list):
        for item in vision_models:
            if not isinstance(item, str):
                continue
            pattern = item.strip()
            if not pattern:
                continue
            if fnmatch.fnmatch(model_lower, pattern.lower()):
                logging.debug(f"[ImageFallback] vision_models matched pattern '{pattern}' for {model}")
                return True

    return False


def _iter_image_items(messages: List[Dict[str, Any]]) -> List[Tuple[int, int, Dict[str, Any]]]:
    items: List[Tuple[int, int, Dict[str, Any]]] = []
    for msg_index, msg in enumerate(messages):
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for item_index, item in enumerate(content):
            if not isinstance(item, dict):
                continue
            item_type = item.get("type")
            if item_type in ("image_url", "image"):
                items.append((msg_index, item_index, item))
    return items


def _normalize_image_item(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    item_type = item.get("type")
    if item_type == "image_url":
        image_url = item.get("image_url", {})
        if isinstance(image_url, dict):
            url = image_url.get("url", "")
        else:
            url = str(image_url or "")
        if not url:
            return None
        return {"type": "image_url", "image_url": {"url": url}}

    if item_type == "image":
        source = item.get("source", {})
        if not isinstance(source, dict):
            return None
        source_type = source.get("type")
        if source_type == "base64":
            media_type = source.get("media_type", "image/png") or "image/png"
            data = source.get("data", "")
            if not data:
                return None
            url = f"data:{media_type};base64,{data}"
            return {"type": "image_url", "image_url": {"url": url}}
        if source_type == "url":
            url = source.get("url", "")
            if not url:
                return None
            return {"type": "image_url", "image_url": {"url": url}}

    return None


def _build_caption_client(config: Dict[str, Any], api_key: str) -> OpenAI:
    base_url = config.get("base_url") or None
    timeout = config.get("timeout", 60)
    http_client = httpx.Client(proxy=None, timeout=timeout)
    return OpenAI(api_key=api_key, base_url=base_url, http_client=http_client)


def _caption_single_image(
    client: OpenAI,
    model: str,
    prompt: str,
    image_item: Dict[str, Any],
    max_tokens: int,
    temperature: float,
) -> str:
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                image_item,
            ],
        }
    ]

    response = client.chat.completions.create(
        model=model,
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
    )

    if not response.choices:
        return ""
    msg = response.choices[0].message
    return (msg.content or "").strip()


def maybe_caption_images(
    messages: List[Dict[str, Any]],
    model: str,
    route_config: Optional[Dict[str, Any]],
    config: Dict[str, Any],
    api_key: str,
) -> Tuple[List[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """
    Replace image items with text descriptions for non-vision models.
    """
    image_cfg = config.get("image_fallback", {}) or {}
    if not image_cfg.get("enabled", False):
        logging.debug("[ImageFallback] disabled in config")
        return messages, None

    if _model_supports_images(model, route_config, config):
        logging.debug(f"[ImageFallback] Skip caption: model supports images ({model})")
        return messages, None

    image_items = _iter_image_items(messages)
    if not image_items:
        logging.debug(f"[ImageFallback] no image items detected, model={model}")
        return messages, None

    caption_model = image_cfg.get("model")
    if not caption_model:
        logging.warning("[ImageFallback] enabled but no model configured; using placeholders.")
        caption_model = None

    caption_api_key = image_cfg.get("api_key") or api_key
    if not caption_api_key:
        logging.warning("[ImageFallback] enabled but no api_key available; using placeholders.")
        caption_model = None

    prompt = image_cfg.get("prompt", "请用中文简洁描述图片内容，只输出描述。")
    max_images = int(image_cfg.get("max_images", 4) or 4)
    max_tokens = int(image_cfg.get("max_tokens", 256) or 256)
    temperature = float(image_cfg.get("temperature", 0.2) or 0.2)

    new_messages = copy.deepcopy(messages)
    captions: Dict[Tuple[int, int], str] = {}

    client = None
    if caption_model and caption_api_key:
        try:
            client = _build_caption_client(image_cfg, caption_api_key)
        except Exception as e:
            logging.warning(f"[ImageFallback] init client failed: {e}")
            client = None

    processed = 0
    for msg_index, item_index, item in image_items:
        processed += 1
        if max_images > 0 and processed > max_images:
            captions[(msg_index, item_index)] = "图片过多，未解析。"
            continue

        normalized = _normalize_image_item(item)
        if not normalized:
            captions[(msg_index, item_index)] = "图片格式无法解析。"
            continue

        if client and caption_model:
            try:
                desc = _caption_single_image(
                    client=client,
                    model=caption_model,
                    prompt=prompt,
                    image_item=normalized,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
                captions[(msg_index, item_index)] = desc or "图片内容无法识别。"
            except Exception as e:
                logging.warning(f"[ImageFallback] caption failed: {e}")
                captions[(msg_index, item_index)] = "图片内容无法识别。"
        else:
            captions[(msg_index, item_index)] = "图片内容无法识别。"

    # Replace image items with text items
    for msg_index, item_index, _ in image_items:
        msg = new_messages[msg_index]
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        if item_index >= len(content):
            continue
        desc = captions.get((msg_index, item_index), "图片内容无法识别。")
        content[item_index] = {"type": "text", "text": f"[图片描述] {desc}"}

    info = {
        "images_total": len(image_items),
        "images_processed": min(len(image_items), max_images) if max_images > 0 else len(image_items),
        "model": caption_model,
    }
    logging.info(
        f"[ImageFallback] converted {info['images_processed']}/{info['images_total']} images using {caption_model or 'placeholders'}"
    )

    return new_messages, info
