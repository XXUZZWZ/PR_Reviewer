"""Parse structured JSON from LLM responses with fallbacks."""

from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger(__name__)


def parse_file_analysis(raw: str) -> dict | None:
    """Parse LLM response into a dict. Handles markdown fences and retries."""

    if not raw or not raw.strip():
        logger.warning("Empty LLM response")
        return None

    # Fast path: direct JSON
    try:
        return json.loads(raw.strip())
    except json.JSONDecodeError:
        pass

    # Fallback 1: extract from markdown code fence
    fence_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", raw, re.DOTALL)
    if fence_match:
        try:
            return json.loads(fence_match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # Fallback 2: find first balanced JSON object
    json_match = _extract_json_object(raw)
    if json_match:
        try:
            return json.loads(json_match)
        except json.JSONDecodeError:
            pass

    logger.warning("Failed to parse LLM response as JSON: %.200s...", raw)
    return None


def _extract_json_object(text: str) -> str | None:
    """Find the outermost {} pair in text."""
    start = text.find("{")
    if start == -1:
        return None

    depth = 0
    in_string = False
    escape = False

    for i in range(start, len(text)):
        ch = text[i]
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"' and not escape:
            in_string = not in_string
        elif not in_string:
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]

    return None
