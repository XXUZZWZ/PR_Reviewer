"""LLM API client via Anthropic SDK (DeepSeek Anthropic-compatible endpoint)."""

from __future__ import annotations

import logging
import time
from anthropic import Anthropic, AnthropicBedrock, APIStatusError, APITimeoutError, RateLimitError
from pr_reviewer.config.settings import LLMConfig

logger = logging.getLogger(__name__)


class LLMClient:
    """Wraps Anthropic SDK, configured for DeepSeek's Anthropic-compatible API."""

    def __init__(self, config: LLMConfig):
        self._config = config
        self._client = Anthropic(
            api_key=config.api_key,
            base_url=config.base_url,
            max_retries=2,
        )

    def analyze_file(
        self,
        system_prompt: str,
        pr_context: str,
        file_context: str,
    ) -> tuple[str, int, int] | None:
        """Send a per-file analysis request. Returns (text, input_tokens, output_tokens) or None."""

        messages = [
            {"role": "user", "content": f"{pr_context}\n\n{file_context}"},
        ]

        for attempt in range(3):
            try:
                response = self._client.messages.create(
                    model=self._config.model,
                    max_tokens=self._config.max_output_tokens,
                    temperature=self._config.temperature,
                    system=[{"type": "text", "text": system_prompt}],
                    messages=messages,
                )

                content = response.content
                if not content:
                    logger.warning("LLM returned empty response (attempt %d)", attempt + 1)
                    continue

                text = "".join(
                    block.text for block in content
                    if hasattr(block, "text")
                )
                inp = response.usage.input_tokens if response.usage else 0
                out = response.usage.output_tokens if response.usage else 0
                return text, inp, out

            except RateLimitError:
                wait = 2 ** attempt * 5
                logger.warning("Rate limited, retrying in %ds...", wait)
                time.sleep(wait)
            except APITimeoutError:
                logger.warning("API timeout (attempt %d)", attempt + 1)
                if attempt < 2:
                    time.sleep(2)
            except APIStatusError as e:
                logger.error("API error (attempt %d): %s", attempt + 1, e)
                if attempt < 2:
                    time.sleep(2)
            except Exception as e:
                logger.error("Unexpected error: %s", e)
                if attempt < 2:
                    time.sleep(2)

        return None
