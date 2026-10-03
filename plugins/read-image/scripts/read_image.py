#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""read-image: base64-encode an image and ask a vision model to describe it.

Flow:
  1. Read the image file and base64-encode it into a data URL.
  2. Call an OpenAI-compatible Responses API endpoint (/responses) with a
     vision-capable model.
  3. Print the model's textual output to stdout, ready for the main model.

Standard library only, Python 3.7+.
"""

from __future__ import print_function

import argparse
import base64
import json
import mimetypes
import os
import sys
import urllib.error
import urllib.request

from pathlib import Path

DEFAULT_MODEL = "gpt-5.6-terra"
DEFAULT_MAX_OUTPUT_TOKENS = 1024
DEFAULT_TIMEOUT_SECONDS = 180
MAX_IMAGE_BYTES = 50 * 1024 * 1024  # 50 MB
CONFIG_FILENAME = "config.env"

MIME_BY_EXT = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".tiff": "image/tiff",
    ".heic": "image/heic",
    ".svg": "image/svg+xml",
}


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


def _resolve_value(arg_value, env_key, config_key=None):
    """Resolve a setting: explicit argument > environment variable > config file."""
    if arg_value is not None and arg_value != "":
        return arg_value
    env_value = os.environ.get(env_key)
    if env_value:
        return env_value
    if config_key is None:
        config_key = env_key
    config_value = _plugin_config().get(config_key)
    if config_value:
        return config_value
    return None


def image_mime_type(image_path):
    """Return a MIME type for the image, preferring a fixed extension map."""
    path = Path(image_path)
    mime = MIME_BY_EXT.get(path.suffix.lower())
    if mime is None:
        mime, _ = mimetypes.guess_type(str(path))
    return mime or "image/png"


def image_to_base64_data_url(image_path):
    """Read an image file and return it as a base64 data URL."""
    path = Path(image_path)
    if not path.is_file():
        raise ValueError("Image file not found: %s" % image_path)
    data = path.read_bytes()
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError(
            "Image is %.1f MB; the limit is %d MB."
            % (len(data) / (1024.0 * 1024.0), MAX_IMAGE_BYTES // (1024 * 1024))
        )
    encoded = base64.b64encode(data).decode("ascii")
    return "data:%s;base64,%s" % (image_mime_type(path), encoded)


def is_url(value):
    """Return True when value looks like an http(s) URL."""
    return isinstance(value, str) and value.startswith(("http://", "https://"))


def is_data_url(value):
    """Return True when value is a base64 data URL (data:image/...;base64,...)."""
    return isinstance(value, str) and value.lower().startswith("data:image/")


def _default_prompt():
    return os.environ.get(
        "READ_IMAGE_PROMPT",
        "Describe this image in detail: main subject, layout, colors, "
        "any visible text, and notable details.",
    )


def call_vision_model(
    image_path,
    prompt=None,
    model=None,
    max_output_tokens=None,
    api_key=None,
    base_url=None,
    timeout=None,
):
    """Base64-encode an image, call a vision model, and return its text.

    Supports two API styles, auto-detected from the base URL:
      - responses (OpenAI Responses API, default for api.openai.com)
      - chat_completions (OpenAI-compatible Chat Completions, e.g. Zhipu
        open.bigmodel.cn); override with $READ_IMAGE_API_STYLE.
    """
    image_is_url = is_url(image_path)
    if image_is_url:
        # Public image URLs are passed through directly.
        data_url = image_path
    elif is_data_url(image_path):
        # Uploaded/pasted image data can be used as-is.
        data_url = image_path
    else:
        data_url = image_to_base64_data_url(image_path)
    prompt = prompt or _default_prompt()
    model = _resolve_value(model, "READ_IMAGE_MODEL") or DEFAULT_MODEL
    api_key = _resolve_value(api_key, "OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "OPENAI_API_KEY is not set. Set it in the environment (or pass "
            "--api-key) so the vision model can be called."
        )
    base_url = (_resolve_value(base_url, "OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip(
        "/"
    )
    if timeout is None:
        try:
            timeout = int(os.environ.get("READ_IMAGE_TIMEOUT", DEFAULT_TIMEOUT_SECONDS))
        except ValueError:
            timeout = DEFAULT_TIMEOUT_SECONDS
    if not max_output_tokens:
        try:
            max_output_tokens = int(_resolve_value(None, "READ_IMAGE_MAX_TOKENS") or DEFAULT_MAX_OUTPUT_TOKENS)
        except ValueError:
            max_output_tokens = DEFAULT_MAX_OUTPUT_TOKENS

    api_style = _resolve_value(None, "READ_IMAGE_API_STYLE")
    if api_style not in ("responses", "chat_completions"):
        api_style = "chat_completions" if "bigmodel.cn" in base_url else "responses"

    if api_style == "chat_completions":
        if image_is_url:
            image_url = data_url
        else:
            image_url_format = _resolve_value(None, "READ_IMAGE_IMAGE_URL_FORMAT")
            if image_url_format not in ("data_url", "base64"):
                # Zhipu's docs send raw base64 as the image_url value.
                image_url_format = "base64" if "bigmodel.cn" in base_url else "data_url"
            image_url = (
                data_url
                if image_url_format == "data_url"
                else data_url.split(",", 1)[1]
            )
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": image_url}},
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
            "max_tokens": max_output_tokens,
        }
        thinking = _resolve_value(None, "READ_IMAGE_THINKING")
        if thinking and str(thinking).strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
            "enabled",
        ):
            payload["thinking"] = {"type": "enabled"}
    else:
        payload = {
            "model": model,
            "input": [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": prompt},
                        {"type": "input_image", "image_url": data_url},
                    ],
                }
            ],
            "max_output_tokens": max_output_tokens,
        }

    endpoint = (
        base_url + "/chat/completions"
        if api_style == "chat_completions"
        else base_url + "/responses"
    )
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + api_key,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError("Vision API HTTP %s: %s" % (error.code, detail[:800]))
    except urllib.error.URLError as error:
        raise RuntimeError("Vision API request failed: %s" % error.reason)

    if api_style == "chat_completions":
        return _extract_chat_completions_text(body)
    return extract_output_text(body)


def _extract_chat_completions_text(body):
    """Extract the assistant text from a Chat Completions response."""
    choices = body.get("choices") or []
    if not choices:
        snippet = json.dumps(body, ensure_ascii=False)[:500]
        raise RuntimeError("No choices in chat completions response: %s" % snippet)
    message = choices[0].get("message") or {}
    content = message.get("content")
    if isinstance(content, str) and content.strip():
        return content
    reasoning = message.get("reasoning_content")
    if isinstance(reasoning, str) and reasoning.strip():
        return reasoning
    snippet = json.dumps(body, ensure_ascii=False)[:500]
    raise RuntimeError("No text content in chat completions response: %s" % snippet)


def extract_output_text(body):
    """Extract the text output from a Responses API response."""
    output_text = body.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text
    pieces = []
    for item in body.get("output", []) or []:
        if isinstance(item, dict) and item.get("type") == "message":
            for content in item.get("content", []) or []:
                if isinstance(content, dict) and content.get("type") in (
                    "output_text",
                    "text",
                ):
                    text = content.get("text")
                    if isinstance(text, str) and text.strip():
                        pieces.append(text)
    if pieces:
        return "\n".join(pieces)
    snippet = json.dumps(body, ensure_ascii=False)[:500]
    raise RuntimeError("No text output in model response: %s" % snippet)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Base64-encode an image and ask a vision model to describe it."
    )
    parser.add_argument("image_path", help="Path to the image file (PNG, JPG, WebP, ...)")
    parser.add_argument(
        "--prompt",
        default=None,
        help="Instruction for the vision model (default: describe the image)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Vision model id (default: $READ_IMAGE_MODEL or %s)" % DEFAULT_MODEL,
    )
    parser.add_argument(
        "--max-output-tokens",
        type=int,
        default=None,
        help="Max output tokens (default: %d)" % DEFAULT_MAX_OUTPUT_TOKENS,
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="OpenAI API key (default: $OPENAI_API_KEY)",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help="API base URL (default: $OPENAI_BASE_URL or https://api.openai.com/v1)",
    )
    args = parser.parse_args(argv)

    try:
        text = call_vision_model(
            args.image_path,
            prompt=args.prompt,
            model=args.model,
            max_output_tokens=args.max_output_tokens,
            api_key=args.api_key,
            base_url=args.base_url,
        )
    except Exception as error:  # noqa: BLE001 - CLI should print a friendly error
        sys.stderr.write("read-image error: %s\n" % error)
        return 1

    sys.stdout.write(text + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
