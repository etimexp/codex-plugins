#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gen-image: call a text-to-image API and save the result.

Flow:
  1. Build the request for the configured provider:
       - DashScope / Qwen (default): POST the native async text2image
         endpoint, then poll /tasks/<id> until the image URL is ready.
       - Any OpenAI-compatible endpoint (e.g. Zhipu GLM): POST
         <base_url>/images/generations.
  2. Handle sync responses (data[0].url / b64_json), Zhipu-style async tasks
     (task_status polling via /async/result/<id>) and DashScope tasks
     (task_status polling via /tasks/<id>).
  3. Save the image bytes to the output directory and return metadata.

Standard library only, Python 3.7+.
"""

from __future__ import print_function

import argparse
import base64
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

DEFAULT_MODEL = "qwen-image-plus"
DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/api/v1"
DEFAULT_SIZE = "1024x1024"
DEFAULT_TIMEOUT_SECONDS = 180
DEFAULT_OUTPUT_DIR = os.path.join(os.path.expanduser("~"), ".codex", "generated_images")
CONFIG_FILENAME = "config.env"

# DashScope-style async text2image + multimodal generation (Qwen image models).
DASHSCOPE_TEXT2IMAGE_PATH = "/services/aigc/text2image/image-synthesis"
DASHSCOPE_MULTIMODAL_PATH = "/services/aigc/multimodal-generation/generation"
DASHSCOPE_TASK_PATH = "/tasks/"
# API key lookup order: DashScope/Qwen first, then generic, then legacy Zhipu.
API_KEY_NAMES = ("DASHSCOPE_API_KEY", "GEN_IMAGE_API_KEY", "OPENAI_API_KEY", "ZHIPU_API_KEY")
DASHSCOPE_MODEL_PREFIXES = ("qwen", "wan", "z-image")

SIZE_RE = re.compile(r"^(auto|\d{2,5}[x*]\d{2,5})$")
SAFE_FILENAME_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

_CONFIG_CACHE = None


def _plugin_config():
    """Load KEY=VALUE pairs from the plugin-root config.env file (cached)."""
    global _CONFIG_CACHE
    if _CONFIG_CACHE is None:
        config = {}
        config_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            CONFIG_FILENAME,
        )
        if os.path.isfile(config_path):
            with open(config_path, "r", encoding="utf-8") as handle:
                for raw_line in handle:
                    line = raw_line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        key, _, value = line.partition("=")
                        key = key.strip()
                        value = value.strip().strip('"').strip("'")
                        if key:
                            config[key] = value
        _CONFIG_CACHE = config
    return _CONFIG_CACHE


def _resolve_value(arg_value, env_key):
    """Resolve a setting: explicit argument > environment variable > config file."""
    if arg_value is not None and str(arg_value).strip() != "":
        return arg_value
    env_value = os.environ.get(env_key)
    if env_value:
        return env_value
    config_value = _plugin_config().get(env_key)
    if config_value:
        return config_value
    return None


def _resolve_api_key(arg_value):
    """Resolve the API key from argument > env vars > config file."""
    if arg_value:
        return arg_value
    for env_key in API_KEY_NAMES:
        value = os.environ.get(env_key)
        if value:
            return value
    for config_key in API_KEY_NAMES:
        value = _plugin_config().get(config_key)
        if value:
            return value
    return None


def _parse_bool(value):
    """Parse a boolean-like value (bool, 'true'/'false', '1'/'0', etc.)."""
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in ("1", "true", "yes", "on"):
        return True
    if text in ("0", "false", "no", "off", ""):
        return False
    raise ValueError("Invalid boolean value %r for watermark" % value)


def _detect_image_ext(data):
    """Return a file extension guessed from image magic bytes."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return ".gif"
    if data[:2] == b"BM":
        return ".bmp"
    return ".png"


def _default_filename(ext=".png"):
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    rand = os.urandom(3).hex()
    return "gen-image-%s-%s%s" % (stamp, rand, ext)


def _http_json(url, payload=None, api_key=None, timeout=DEFAULT_TIMEOUT_SECONDS):
    """Send an HTTP request and return the parsed JSON body."""
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = "Bearer " + api_key
    data = None
    method = "GET"
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        method = "POST"
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError("Image API HTTP %s: %s" % (error.code, detail[:800]))
    except urllib.error.URLError as error:
        raise RuntimeError("Image API request failed: %s" % error.reason)


def _download_image(url, api_key, timeout=DEFAULT_TIMEOUT_SECONDS):
    """Download image bytes from a URL, sending the API key when set."""
    headers = {}
    if api_key:
        headers["Authorization"] = "Bearer " + api_key
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError("Image download HTTP %s: %s" % (error.code, detail[:400]))
    except urllib.error.URLError as error:
        raise RuntimeError("Image download failed: %s" % error.reason)


def _call_image_endpoint(base_url, payload, api_key, timeout):
    """POST /images/generations and follow Zhipu-style async tasks."""
    body = _http_json(
        base_url.rstrip("/") + "/images/generations",
        payload,
        api_key,
        timeout,
    )
    task_id = body.get("id")
    task_status = body.get("task_status")
    if task_id and task_status:
        deadline = time.time() + timeout
        while time.time() < deadline:
            time.sleep(2)
            result = _http_json(
                base_url.rstrip("/") + "/async/result/" + str(task_id),
                api_key=api_key,
                timeout=timeout,
            )
            status = result.get("task_status")
            if status in ("SUCCESS", "SUCCEEDED"):
                body = result
                break
            if status in ("FAIL", "FAILED"):
                raise RuntimeError(
                    "Image generation task failed: %s"
                    % json.dumps(result, ensure_ascii=False)[:500]
                )
        else:
            raise RuntimeError("Image generation task timed out after %s seconds" % timeout)
    return body


def _post_json(url, payload, api_key, timeout, extra_headers=None):
    """POST JSON and return (status_code, parsed_body) without raising on 4xx/5xx."""
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = "Bearer " + api_key
    headers.update(extra_headers or {})
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), method="POST", headers=headers
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = getattr(response, "status", response.getcode())
            raw = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as error:
        status = error.code
        raw = error.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as error:
        raise RuntimeError("Image API request failed: %s" % error.reason)
    try:
        return status, json.loads(raw)
    except ValueError:
        return status, {"_raw": raw[:800]}


def _get_json(url, api_key, timeout):
    """GET JSON and return (status_code, parsed_body) without raising on 4xx/5xx."""
    headers = {}
    if api_key:
        headers["Authorization"] = "Bearer " + api_key
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = getattr(response, "status", response.getcode())
            raw = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as error:
        status = error.code
        raw = error.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as error:
        raise RuntimeError("Image API request failed: %s" % error.reason)
    try:
        return status, json.loads(raw)
    except ValueError:
        return status, {"_raw": raw[:800]}


def _is_dashscope(base_url, model):
    """True when the request should use the DashScope (Qwen) native API."""
    if "dashscope" in (base_url or "").lower():
        return True
    lowered = (model or "").lower()
    return lowered.startswith(DASHSCOPE_MODEL_PREFIXES)


def _dashscope_size(size):
    """DashScope expects sizes such as 1024*1024 (asterisk, not 'x')."""
    return size.replace("x", "*").replace("X", "*")


def _dashscope_parameters(size, watermark):
    """Build the DashScope `parameters` object."""
    parameters = {"n": 1}
    if size and size != "auto":
        parameters["size"] = _dashscope_size(size)
    if watermark is not None:
        parameters["watermark"] = _parse_bool(watermark)
    return parameters


def _dashscope_result(body):
    """Normalize a DashScope task/multimodal payload into the {data:[...]} shape."""
    output = body.get("output") or {}
    for item in output.get("results") or []:
        if isinstance(item, dict) and isinstance(item.get("url"), str) and item["url"]:
            return {"data": [{"url": item["url"]}]}
    choices = output.get("choices") or body.get("choices") or []
    for choice in choices:
        content = ((choice or {}).get("message") or {}).get("content") or []
        for block in content:
            if not isinstance(block, dict):
                continue
            image = block.get("image")
            if isinstance(image, str) and image.startswith(("http://", "https://")):
                return {"data": [{"url": image}]}
            if isinstance(image, str) and image:
                return {"data": [{"b64_json": image}]}
    raise RuntimeError(
        "Unsupported DashScope image response: %s"
        % json.dumps(body, ensure_ascii=False)[:500]
    )


def _dashscope_poll(base_url, task_id, api_key, timeout):
    """Poll /tasks/<id> until the image task succeeds."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(2)
        status, body = _get_json(
            base_url.rstrip("/") + DASHSCOPE_TASK_PATH + str(task_id), api_key, timeout
        )
        if status != 200:
            continue
        state = (body.get("output") or {}).get("task_status")
        if state in ("SUCCEEDED", "SUCCESS"):
            return _dashscope_result(body)
        if state in ("FAILED", "FAIL", "CANCELED", "UNKNOWN"):
            raise RuntimeError(
                "Image generation task failed: %s"
                % json.dumps(body, ensure_ascii=False)[:500]
            )
    raise RuntimeError("Image generation task timed out after %s seconds" % timeout)


def _dashscope_multimodal(base_url, model, prompt, size, watermark, api_key, timeout):
    """Synchronous fallback for models served by the multimodal role-play endpoint."""
    status, body = _post_json(
        base_url.rstrip("/") + DASHSCOPE_MULTIMODAL_PATH,
        {
            "model": model,
            "input": {"messages": [{"role": "user", "content": [{"text": prompt}]}]},
            "parameters": _dashscope_parameters(size, watermark),
        },
        api_key,
        timeout,
    )
    if status != 200:
        raise RuntimeError(
            "Image API HTTP %s: %s" % (status, json.dumps(body, ensure_ascii=False)[:500])
        )
    return _dashscope_result(body)


def _call_dashscope(base_url, model, prompt, size, watermark, api_key, timeout):
    """Generate an image through the DashScope (Qwen) API."""
    status, body = _post_json(
        base_url.rstrip("/") + DASHSCOPE_TEXT2IMAGE_PATH,
        {
            "model": model,
            "input": {"prompt": prompt},
            "parameters": _dashscope_parameters(size, watermark),
        },
        api_key,
        timeout,
        {"X-DashScope-Async": "enable"},
    )
    if status == 200:
        task_id = (body.get("output") or {}).get("task_id")
        if task_id:
            return _dashscope_poll(base_url, task_id, api_key, timeout)
        return _dashscope_result(body)
    code = str(body.get("code", ""))
    message = str(body.get("message", ""))
    if code == "InvalidParameter" and "url error" in message.lower():
        # Model lives on the multimodal-generation endpoint instead.
        return _dashscope_multimodal(
            base_url, model, prompt, size, watermark, api_key, timeout
        )
    raise RuntimeError(
        "Image API HTTP %s: %s" % (status, json.dumps(body, ensure_ascii=False)[:500])
    )


def _pick_image_bytes(body):
    """Return (kind, value) from an image API response body."""
    data_list = body.get("data")
    if not isinstance(data_list, list) or not data_list:
        snippet = json.dumps(body, ensure_ascii=False)[:500]
        raise RuntimeError("No image data in API response: %s" % snippet)
    item = data_list[0] if isinstance(data_list[0], dict) else {}
    for key in ("b64_json", "base64"):
        value = item.get(key)
        if isinstance(value, str) and value:
            try:
                return ("bytes", base64.b64decode(value))
            except Exception:
                raise RuntimeError("API returned invalid base64 image data")
    for key in ("url", "image_url"):
        value = item.get(key)
        if isinstance(value, str) and value.startswith(("http://", "https://")):
            return ("url", value)
    snippet = json.dumps(body, ensure_ascii=False)[:500]
    raise RuntimeError("Unsupported image API response: %s" % snippet)


def _safe_filename(raw_name, ext):
    """Sanitize a user-provided filename and ensure it ends with the image extension."""
    if not raw_name:
        return _default_filename(ext)
    cleaned = SAFE_FILENAME_RE.sub("-", raw_name).strip(" .")
    if not cleaned:
        return _default_filename(ext)
    lowered = cleaned.lower()
    if not lowered.endswith((ext, ".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")):
        cleaned += ext
    return cleaned


def generate_image(
    prompt,
    size=None,
    filename=None,
    output_dir=None,
    model=None,
    api_key=None,
    base_url=None,
    timeout=None,
    watermark=None,
):
    """Generate an image from text and save it locally.

    Returns a dict with image_path, file_name, size_bytes, model, prompt and
    output_dir. Resolution order for settings: explicit argument > environment
    variable > plugin config.env. The optional `watermark` argument controls
    the API's watermark parameter (True/False); when unset it defaults to
    False (no watermark). Set watermark=True (or GEN_IMAGE_WATERMARK=true) to
    add a watermark. Note: disabling the watermark may require signing a
    disclaimer on the platform.
    """
    prompt = (prompt or "").strip()
    if not prompt:
        raise ValueError("prompt is required and must not be empty")

    model = _resolve_value(model, "GEN_IMAGE_MODEL") or DEFAULT_MODEL
    api_key = _resolve_api_key(api_key)
    if not api_key:
        raise RuntimeError(
            "No API key configured. Set DASHSCOPE_API_KEY (or GEN_IMAGE_API_KEY "
            "/ OPENAI_API_KEY / ZHIPU_API_KEY) in the environment or in the "
            "plugin config.env file."
        )
    base_url = (_resolve_value(base_url, "GEN_IMAGE_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
    size = _resolve_value(size, "GEN_IMAGE_SIZE") or DEFAULT_SIZE
    if SIZE_RE.match(size) is None:
        raise ValueError(
            "Invalid size %r; use a format like 1024x1024, 1536x1024, 1024*1024, or auto" % size
        )
    output_dir = _resolve_value(output_dir, "GEN_IMAGE_OUTPUT_DIR") or DEFAULT_OUTPUT_DIR
    if timeout is None:
        try:
            timeout = int(os.environ.get("GEN_IMAGE_TIMEOUT") or DEFAULT_TIMEOUT_SECONDS)
        except ValueError:
            timeout = DEFAULT_TIMEOUT_SECONDS

    watermark = _resolve_value(watermark, "GEN_IMAGE_WATERMARK")
    if watermark is None:
        watermark = False  # 默认不加水印

    if _is_dashscope(base_url, model):
        body = _call_dashscope(
            base_url, model, prompt, size, watermark, api_key, timeout
        )
    else:
        payload = {"model": model, "prompt": prompt, "watermark": _parse_bool(watermark)}
        if size != "auto":
            payload["size"] = size
        body = _call_image_endpoint(base_url, payload, api_key, timeout)
    kind, value = _pick_image_bytes(body)
    if kind == "url":
        data = _download_image(value, api_key, timeout)
        from urllib.parse import urlparse
        path_suffix = Path(urlparse(value).path).suffix.lower()
        ext = path_suffix if path_suffix in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp") else None
        ext = ext or _detect_image_ext(data)
    else:
        data = value
        ext = _detect_image_ext(data)

    out_path = Path(output_dir).expanduser().resolve()
    out_path.mkdir(parents=True, exist_ok=True)
    file_name = _safe_filename(filename, ext)
    target = out_path / file_name
    target.write_bytes(data)

    return {
        "image_path": str(target),
        "file_name": target.name,
        "size_bytes": len(data),
        "model": model,
        "prompt": prompt,
        "output_dir": str(out_path),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Generate an image from a text prompt via DashScope (Qwen) or "
        "any OpenAI-compatible image API."
    )
    parser.add_argument("prompt", help="Text description of the image to generate")
    parser.add_argument("--size", default=None, help="Image size, e.g. 1024x1024 (default: $GEN_IMAGE_SIZE)")
    parser.add_argument("--filename", default=None, help="Output file name (optional)")
    parser.add_argument("--output-dir", default=None, help="Output directory (optional)")
    parser.add_argument(
        "--model",
        default=None,
        help="Model id (default: $GEN_IMAGE_MODEL or qwen-image-plus; "
        "also usable: qwen-image, qwen-image-3.0-pro, glm-image)",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="API key (default: $DASHSCOPE_API_KEY / $GEN_IMAGE_API_KEY)",
    )
    parser.add_argument("--base-url", default=None, help="API base URL (default: $GEN_IMAGE_BASE_URL)")
    parser.add_argument("--timeout", type=int, default=None, help="Timeout in seconds (default: 180)")
    parser.add_argument(
        "--watermark",
        default=None,
        help="Whether to add a watermark: true/false (default: false, no watermark)",
    )
    args = parser.parse_args(argv)

    try:
        result = generate_image(
            args.prompt,
            size=args.size,
            filename=args.filename,
            output_dir=args.output_dir,
            model=args.model,
            api_key=args.api_key,
            base_url=args.base_url,
            timeout=args.timeout,
            watermark=args.watermark,
        )
    except Exception as error:  # noqa: BLE001 - CLI should print a friendly error
        sys.stderr.write("gen-image error: %s\n" % error)
        return 1

    sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
