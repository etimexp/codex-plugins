#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Minimal MCP (stdio) server exposing the read_image tool.

Implements just enough of the Model Context Protocol (JSON-RPC 2.0 over
stdio, newline-delimited) to list and call the `read_image` tool:

  read_image(image_path, prompt?, model?, max_output_tokens?)

The tool base64-encodes the image, calls an OpenAI-compatible vision model
through the Responses API, and returns the model's text to the client.

Standard library only, Python 3.7+.
"""

from __future__ import print_function

import json
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import read_image  # noqa: E402

SERVER_NAME = "read-image"
SERVER_VERSION = "0.1.0"
DEFAULT_PROTOCOL_VERSION = "2025-06-18"

TOOL_SCHEMA = {
    "name": "read_image",
    "description": (
        "Read an image file with a vision model and return the result as text. "
        "Base64-encodes the image, sends it to an OpenAI-compatible vision "
        "model (OpenAI Responses API or Chat Completions, e.g. Zhipu GLM) and "
        "returns the description to the caller. Requires OPENAI_API_KEY."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "image_path": {
                "type": "string",
                "description": (
                    "Path to a local image file (PNG, JPG, JPEG, WebP, BMP, GIF, "
                    "TIFF), an http(s) URL of a public image, or a base64 data "
                    "URL (data:image/...;base64,...) from an uploaded image."
                ),
            },
            "prompt": {
                "type": "string",
                "description": (
                    "Instruction for the vision model, e.g. "
                    "'Extract all text from this screenshot verbatim.'"
                ),
            },
            "model": {
                "type": "string",
                "description": (
                    "Vision model id (default: $READ_IMAGE_MODEL or the "
                    "READ_IMAGE_MODEL value in config.env)."
                ),
            },
            "max_output_tokens": {
                "type": "integer",
                "description": "Maximum number of output tokens (default: 1024).",
            },
        },
        "required": ["image_path"],
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


def _handle_tools_call(params):
    name = params.get("name")
    arguments = params.get("arguments") or {}
    if name != "read_image":
        raise ValueError("Unknown tool: %s" % name)
    image_path = arguments.get("image_path")
    if not image_path:
        raise ValueError("Missing required argument: image_path")
    text = read_image.call_vision_model(
        image_path,
        prompt=arguments.get("prompt"),
        model=arguments.get("model"),
        max_output_tokens=arguments.get("max_output_tokens"),
    )
    return {"content": [{"type": "text", "text": text}], "isError": False}


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
