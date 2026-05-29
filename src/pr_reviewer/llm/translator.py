"""Translate review findings from English to Chinese via LLM."""

from __future__ import annotations

import json
import logging
import time

from anthropic import Anthropic, APIStatusError, APITimeoutError, RateLimitError

from pr_reviewer.config.settings import LLMConfig
from pr_reviewer.report.models import FileAnalysis

logger = logging.getLogger(__name__)

TRANSLATE_SYSTEM = """Translate code review text from English to Chinese (Simplified).
Rules:
- Keep technical terms in English (API, JSON, CI, workflow, null, async, refactor, etc.)
- Keep code symbols, variable names, file paths unchanged
- Translate naturally like a professional Chinese software engineer
- Do NOT translate severity words (CRITICAL, HIGH, MEDIUM, LOW, INFO)
Return ONLY a JSON object with the same keys, values translated to Chinese."""


def translate_file_analysis(fa: FileAnalysis, config: LLMConfig) -> None:
    """Translate summary and findings in-place. Uses flash model for cost."""

    # Collect translatable texts
    texts: dict[str, str] = {}
    if fa.summary.strip():
        texts["summary"] = fa.summary
    if fa.dependencies_impact.strip():
        texts["dependencies_impact"] = fa.dependencies_impact
    if fa.linter_correlation.strip():
        texts["linter_correlation"] = fa.linter_correlation

    finding_texts: list[dict[str, str]] = []
    for f in fa.findings:
        ft = {}
        if f.title.strip():
            ft["title"] = f.title
        if f.description.strip():
            ft["description"] = f.description
        if f.suggestion.strip():
            ft["suggestion"] = f.suggestion
        finding_texts.append(ft)

    if not texts and not any(ft for ft in finding_texts):
        return

    payload = json.dumps({**texts, "findings": finding_texts}, ensure_ascii=False)

    # Use flash model for cheaper translation
    client = Anthropic(
        api_key=config.api_key,
        base_url=config.base_url,
        max_retries=1,
    )

    for attempt in range(2):
        try:
            response = client.messages.create(
                model="deepseek-v4-flash",
                max_tokens=4096,
                temperature=0.1,
                system=[{"type": "text", "text": TRANSLATE_SYSTEM}],
                messages=[{"role": "user", "content": payload}],
            )
            text = "".join(
                b.text for b in response.content if hasattr(b, "text")
            )
            result = _parse_json(text)
            if not result:
                return

            if "summary" in result:
                fa.summary_zh = str(result["summary"])
            if "dependencies_impact" in result:
                fa.dependencies_impact_zh = str(result["dependencies_impact"])
            if "linter_correlation" in result:
                fa.linter_correlation_zh = str(result["linter_correlation"])

            tr_findings = result.get("findings", [])
            for i, tr in enumerate(tr_findings):
                if i >= len(fa.findings):
                    break
                if isinstance(tr, dict):
                    if "title" in tr:
                        fa.findings[i].title_zh = str(tr["title"])
                    if "description" in tr:
                        fa.findings[i].description_zh = str(tr["description"])
                    if "suggestion" in tr:
                        fa.findings[i].suggestion_zh = str(tr["suggestion"])
            return

        except RateLimitError:
            time.sleep(3 * (attempt + 1))
        except (APITimeoutError, APIStatusError) as e:
            logger.warning("Translation API error: %s", e)
            if attempt < 1:
                time.sleep(2)
        except Exception as e:
            logger.warning("Translation error for %s: %s", fa.file_path, e)
            return


def _parse_json(raw: str) -> dict | None:
    import re
    raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    return None
