#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Minimal MCP (stdio) server exposing the generate_image tool.

Implements just enough of the Model Context Protocol (JSON-RPC 2.0 over
stdio, newline-delimited) to list and call the `generate_image` tool:

  generate_image(prompt, size?, filename?, output_dir?, model?, watermark?)

The tool calls a text-to-image API (default: DashScope / Qwen, model
qwen-image-plus, configurable via GEN_IMAGE_MODEL / config.env; Zhipu GLM and
other OpenAI-compatible endpoints are also supported), saves the image
locally, and returns both a text summary with the local path and an embedded
image content block so the client can display it.

Standard library only, Python 3.7+.
"""

from __future__ import print_function

import base64
import json
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gen_image  # noqa: E402

SERVER_NAME = "gen-image"
SERVER_VERSION = "0.1.0"
DEFAULT_PROTOCOL_VERSION = "2025-06-18"

TOOL_SCHEMA = {
    "name": "generate_image",
    "description": (
        "Generate an image from a text description (default provider: Alibaba "
        "DashScope, default model: qwen-image-plus; model is configurable via "
        "GEN_IMAGE_MODEL, e.g. qwen-image, qwen-image-3.0-pro, or glm-image for "
        "Zhipu). The image is saved to the local output directory and returned "
        "to the caller both as an embedded image and as a local file path. "
        "Requires DASHSCOPE_API_KEY (or GEN_IMAGE_API_KEY / OPENAI_API_KEY / "
        "ZHIPU_API_KEY)."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": (
                    "Text description of the image to generate: subject, scene, "
                    "style, composition, colors, and any visible text."
                ),
            },
            "size": {
                "type": "string",
                "description": (
                    "Image size passed to the API, e.g. 1024x1024, 1536x1024, "
                    "1024x1536, or auto (default: $GEN_IMAGE_SIZE or 1024x1024)."
                ),
            },
            "filename": {
                "type": "string",
                "description": "Optional output file name (a unique name is generated otherwise).",
            },
            "output_dir": {
                "type": "string",
                "description": (
                    "Optional local directory to save the image "
                    "(default: $GEN_IMAGE_OUTPUT_DIR or ~/.codex/generated_images)."
                ),
            },
            "model": {
                "type": "string",
                "description": (
                    "Model id (default: $GEN_IMAGE_MODEL or qwen-image-plus). "
                    "Qwen options include qwen-image, qwen-image-plus, "
                    "qwen-image-3.0 and qwen-image-3.0-pro. OpenAI-compatible "
                    "providers such as Zhipu (glm-image, cogview-4) also work "
                    "when GEN_IMAGE_BASE_URL points at their endpoint."
                ),
            },
            "watermark": {
                "type": "boolean",
                "description": (
                    "Whether to add a watermark to the generated image. "
                    "Defaults to false (no watermark). Pass true to add one, "
                    "or set GEN_IMAGE_WATERMARK=true in config.env. Note: "
                    "no-watermark output may require signing a disclaimer on "
                    "the platform."
                ),
            },
        },
        "required": ["prompt"],
    },
}


def _read_messages():
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except (ValueError, json.JSONDecodeError):
            continue


def _send(message):
    sys.stdout.write(json.dumps(message, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _result(message_id, result):
    _send({"jsonrpc": "2.0", "id": message_id, "result": result})


def _error(message_id, code, text):
    _send(
        {
            "jsonrpc": "2.0",
            "id": message_id,
            "error": {"code": code, "message": text},
        }
    )


def _mime_for_path(image_path):
    lowered = image_path.lower()
    if lowered.endswith(".jpg") or lowered.endswith(".jpeg"):
        return "image/jpeg"
    if lowered.endswith(".webp"):
        return "image/webp"
    if lowered.endswith(".gif"):
        return "image/gif"
    return "image/png"


def _handle_tools_call(params):
    name = params.get("name")
    arguments = params.get("arguments") or {}
    if name != "generate_image":
        raise ValueError("Unknown tool: %s" % name)
    prompt = arguments.get("prompt")
    if not prompt or not str(prompt).strip():
        raise ValueError("Missing required argument: prompt")
    result = gen_image.generate_image(
        prompt,
        size=arguments.get("size"),
        filename=arguments.get("filename"),
        output_dir=arguments.get("output_dir"),
        model=arguments.get("model"),
        watermark=arguments.get("watermark"),
    )
    image_path = result["image_path"]
    with open(image_path, "rb") as handle:
        encoded = base64.b64encode(handle.read()).decode("ascii")
    summary = (
        "图片已生成。\n"
        "本地路径: %s\n"
        "模型: %s\n"
        "输出目录: %s\n"
        "请在回复中用 Markdown 展示该图片(绝对路径),并提供下载链接。"
        % (image_path, result["model"], result["output_dir"])
    )
    return {
        "content": [
            {"type": "text", "text": summary},
            {"type": "image", "data": encoded, "mimeType": _mime_for_path(image_path)},
        ],
        "isError": False,
    }


def _handle_request(message):
    method = message.get("method")
    message_id = message.get("id")

    if method == "initialize":
        client_version = (message.get("params") or {}).get("protocolVersion")
        protocol_version = (
            client_version
            if isinstance(client_version, str) and client_version
            else DEFAULT_PROTOCOL_VERSION
        )
        _result(
            message_id,
            {
                "protocolVersion": protocol_version,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            },
        )
        return

    if method == "notifications/initialized":
        return

    if method == "ping":
        _result(message_id, {})
        return

    if method == "tools/list":
        _result(message_id, {"tools": [TOOL_SCHEMA]})
        return

    if method == "tools/call":
        try:
            result = _handle_tools_call(message.get("params") or {})
        except Exception as error:  # noqa: BLE001
            text = "%s: %s" % (type(error).__name__, error)
            result = {
                "content": [{"type": "text", "text": text}],
                "isError": True,
            }
        _result(message_id, result)
        return

    if method == "resources/list":
        _result(message_id, {"resources": []})
        return

    if message_id is not None:
        _error(message_id, -32601, "Method not found: %s" % method)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    for message in _read_messages():
        if not isinstance(message, dict):
            continue
        try:
            _handle_request(message)
        except Exception:  # noqa: BLE001
            if message.get("id") is not None:
                _error(message.get("id"), -32603, traceback.format_exc())


if __name__ == "__main__":
    main()
