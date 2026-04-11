from __future__ import annotations

import json
import time
from collections import deque
from pathlib import Path
from typing import Any

from loguru import logger

from src.models.schema import Candidate


class AIResolver:
    """Resolves ambiguous fields using OpenAI API calls."""

    PROMPTS_DIR = Path(__file__).parent.parent / "prompts"

    def __init__(self, settings: Any = None) -> None:
        self._settings = settings
        self._client: Any = None
        self._model = "gpt-4o"
        self._timeout = 60
        self._max_retries = 3
        self._tpm_budget = 80000
        self._enabled = True

        if settings and hasattr(settings, "ai"):
            ai = settings.ai
            self._model = getattr(ai, "model", "gpt-4o")
            self._timeout = getattr(ai, "timeout_sec", 60)
            self._max_retries = getattr(ai, "max_retries", 3)
            self._tpm_budget = getattr(ai, "tpm_budget", 80000)
            self._enabled = getattr(ai, "enabled", True)

        # Rolling window for TPM tracking: list of (timestamp, tokens_used)
        self._token_usage: deque[tuple[float, int]] = deque()

    def _get_client(self) -> Any:
        """Lazily initialize OpenAI client."""
        if self._client is not None:
            return self._client

        if not self._enabled:
            return None

        try:
            from openai import OpenAI
            self._client = OpenAI()
        except ImportError:
            logger.error("openai package not installed")
            return None
        except Exception as e:
            logger.error(f"Failed to initialize OpenAI client: {e}")
            return None

        return self._client

    def _load_prompt(self, name: str) -> str:
        """Load a prompt template from file."""
        prompt_file = self.PROMPTS_DIR / f"{name}.txt"
        if prompt_file.exists():
            return prompt_file.read_text(encoding="utf-8")
        return ""

    def _check_tpm_budget(self, estimated_tokens: int) -> bool:
        """Check if we have remaining TPM budget. Prune entries older than 60s."""
        now = time.time()
        # Remove entries older than 60 seconds
        while self._token_usage and now - self._token_usage[0][0] > 60:
            self._token_usage.popleft()

        used = sum(t for _, t in self._token_usage)
        return (used + estimated_tokens) <= self._tpm_budget

    def _record_token_usage(self, tokens: int) -> None:
        """Record token usage for TPM tracking."""
        self._token_usage.append((time.time(), tokens))

    def _call_api(
        self,
        messages: list[dict],
        max_tokens: int = 500,
    ) -> str | None:
        """Make an OpenAI API call with retry and rate limiting."""
        client = self._get_client()
        if client is None:
            return None

        estimated_tokens = sum(len(m.get("content", "")) // 4 for m in messages) + max_tokens
        if not self._check_tpm_budget(estimated_tokens):
            logger.warning("TPM budget exceeded, waiting...")
            time.sleep(10)

        for attempt in range(self._max_retries):
            try:
                response = client.chat.completions.create(
                    model=self._model,
                    messages=messages,
                    temperature=0,
                    max_tokens=max_tokens,
                    timeout=self._timeout,
                )
                content = response.choices[0].message.content
                tokens_used = response.usage.total_tokens if response.usage else estimated_tokens
                self._record_token_usage(tokens_used)
                return content

            except Exception as e:
                error_str = str(e)
                if "429" in error_str or "rate_limit" in error_str.lower():
                    wait_time = 30 * (attempt + 1)
                    logger.warning(f"Rate limited (attempt {attempt + 1}), waiting {wait_time}s...")
                    time.sleep(wait_time)
                elif attempt < self._max_retries - 1:
                    logger.warning(f"API call failed (attempt {attempt + 1}): {e}")
                    time.sleep(5)
                else:
                    logger.error(f"API call failed after {self._max_retries} attempts: {e}")

        return None

    def _parse_json_response(self, response: str | None) -> dict | None:
        """Parse JSON from API response, handling markdown code blocks."""
        if not response:
            return None
        try:
            # Strip markdown code blocks
            clean = response.strip()
            if clean.startswith("```"):
                lines = clean.split("\n")
                clean = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
            return json.loads(clean)
        except json.JSONDecodeError:
            # Try to extract JSON from text
            import re
            m = re.search(r"\{.*\}", response, re.DOTALL)
            if m:
                try:
                    return json.loads(m.group(0))
                except json.JSONDecodeError:
                    pass
            logger.warning(f"Failed to parse JSON response: {response[:200]}")
            return None

    def classify_doc_type(
        self,
        text_snippet: str,
        filename: str,
        candidates: list[str],
    ) -> str:
        """Use AI to classify document type."""
        if not self._enabled:
            return "UNKNOWN"

        prompt_template = self._load_prompt("classify_doc")
        if not prompt_template:
            return "UNKNOWN"

        user_content = (
            f"Filename: {filename}\n"
            f"Candidate types: {', '.join(candidates)}\n"
            f"Text (first 1000 chars):\n{text_snippet[:1000]}"
        )

        messages = [
            {"role": "system", "content": prompt_template},
            {"role": "user", "content": user_content},
        ]

        response = self._call_api(messages, max_tokens=200)
        parsed = self._parse_json_response(response)

        if parsed and "doc_type" in parsed:
            return str(parsed["doc_type"])

        return "UNKNOWN"

    def resolve_company_role(
        self,
        text_snippet: str,
        companies: list[str],
    ) -> dict[str, str]:
        """Use AI to determine buyer/seller company roles."""
        if not self._enabled or not companies:
            return {"buyer": "", "seller": ""}

        prompt_template = self._load_prompt("resolve_company_role")
        if not prompt_template:
            return {"buyer": "", "seller": ""}

        user_content = (
            f"Companies found: {', '.join(companies)}\n"
            f"Text snippet:\n{text_snippet[:1500]}"
        )

        messages = [
            {"role": "system", "content": prompt_template},
            {"role": "user", "content": user_content},
        ]

        response = self._call_api(messages, max_tokens=300)
        parsed = self._parse_json_response(response)

        if parsed:
            return {
                "buyer": str(parsed.get("buyer", "")),
                "seller": str(parsed.get("seller", "")),
            }

        return {"buyer": "", "seller": ""}

    def resolve_amount_conflict(
        self,
        candidates: list[Candidate],
        field_name: str,
        text_snippet: str,
    ) -> Candidate | None:
        """Use AI to resolve conflicting amount candidates."""
        if not self._enabled or not candidates:
            return None

        prompt_template = self._load_prompt("resolve_amount")
        if not prompt_template:
            return None

        candidates_text = "\n".join(
            f"{i}. value={c.value}, label={c.label}, context={c.evidence_text[:100]}"
            for i, c in enumerate(candidates)
        )
        user_content = (
            f"Field: {field_name}\n"
            f"Candidates:\n{candidates_text}\n"
            f"Text context:\n{text_snippet[:1000]}"
        )

        messages = [
            {"role": "system", "content": prompt_template},
            {"role": "user", "content": user_content},
        ]

        response = self._call_api(messages, max_tokens=200)
        parsed = self._parse_json_response(response)

        if parsed and "selected_candidate_index" in parsed:
            idx = int(parsed["selected_candidate_index"])
            if 0 <= idx < len(candidates):
                return candidates[idx]

        return None

    def resolve_date_conflict(
        self,
        candidates: list[Candidate],
        text_snippet: str,
        image_b64: str | None = None,
    ) -> Candidate | None:
        """Use AI to resolve conflicting date candidates."""
        if not self._enabled or not candidates:
            return None

        prompt_template = self._load_prompt("resolve_date")
        if not prompt_template:
            return None

        candidates_text = "\n".join(
            f"{i}. value={c.value}, label={c.label}, context={c.evidence_text[:100]}"
            for i, c in enumerate(candidates)
        )
        user_content = (
            f"Candidates:\n{candidates_text}\n"
            f"Text context:\n{text_snippet[:1000]}"
        )

        messages: list[dict] = [
            {"role": "system", "content": prompt_template},
        ]

        if image_b64:
            messages.append({
                "role": "user",
                "content": [
                    {"type": "text", "text": user_content},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
                ],
            })
        else:
            messages.append({"role": "user", "content": user_content})

        response = self._call_api(messages, max_tokens=200)
        parsed = self._parse_json_response(response)

        if parsed and "selected_index" in parsed:
            idx = int(parsed["selected_index"])
            if 0 <= idx < len(candidates):
                return candidates[idx]

        return None

    def summarize(
        self,
        doc_type: str,
        fields: dict,
        text_snippet: str,
    ) -> str:
        """Generate a one-sentence Chinese summary for the document."""
        if not self._enabled:
            return ""

        prompt_template = self._load_prompt("summarize_doc")
        if not prompt_template:
            return ""

        fields_text = "\n".join(f"{k}: {v}" for k, v in fields.items() if v)
        user_content = (
            f"Document type: {doc_type}\n"
            f"Key fields:\n{fields_text}\n"
            f"Text snippet:\n{text_snippet[:500]}"
        )

        messages = [
            {"role": "system", "content": prompt_template},
            {"role": "user", "content": user_content},
        ]

        response = self._call_api(messages, max_tokens=150)
        parsed = self._parse_json_response(response)

        if parsed and "summary" in parsed:
            return str(parsed["summary"])

        return ""
