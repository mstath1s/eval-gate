"""Model providers.

Two implementations, one interface:

* ``MistralProvider`` — real calls to the Mistral chat completions API, standard library only.
* ``FakeProvider`` — scripted answers, so the harness and the gate can be exercised (and tested
  in CI) without an API key. Its latency is simulated: a run against it measures the harness,
  not the model.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

from .pricing import cost_usd
from .types import Completion

MISTRAL_URL = "https://api.mistral.ai/v1/chat/completions"


class ProviderError(RuntimeError):
    pass


class MistralProvider:
    """Mistral chat completions over HTTPS. One retry on 429 and 5xx."""

    name = "mistral"

    def __init__(
        self,
        api_key: str | None = None,
        pricing: dict | None = None,
        url: str = MISTRAL_URL,
        timeout_s: float = 60.0,
        max_attempts: int = 2,
    ) -> None:
        self.api_key = api_key or os.environ.get("MISTRAL_API_KEY", "")
        if not self.api_key:
            raise ProviderError(
                "MISTRAL_API_KEY is not set. Use --offline to run the harness without a key."
            )
        self.pricing = pricing or {}
        self.url = url
        self.timeout_s = timeout_s
        self.max_attempts = max_attempts

    def complete(self, messages: list[dict], model: str, temperature: float = 0.0) -> Completion:
        body = json.dumps(
            {"model": model, "messages": messages, "temperature": temperature}
        ).encode("utf-8")
        request = urllib.request.Request(
            self.url,
            data=body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )

        last_error = ""
        for attempt in range(1, self.max_attempts + 1):
            started = time.monotonic()
            try:
                with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                elapsed = int((time.monotonic() - started) * 1000)
                usage = payload.get("usage", {}) or {}
                prompt_tokens = int(usage.get("prompt_tokens", 0) or 0)
                completion_tokens = int(usage.get("completion_tokens", 0) or 0)
                text = ""
                choices = payload.get("choices") or []
                if choices:
                    text = (choices[0].get("message") or {}).get("content") or ""
                return Completion(
                    text=text,
                    model=payload.get("model", model),
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    latency_ms=elapsed,
                    attempts=attempt,
                    cost_usd=cost_usd(self.pricing, model, prompt_tokens, completion_tokens),
                )
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", "replace")[:400]
                last_error = f"HTTP {exc.code}: {detail}"
                if exc.code == 429 or 500 <= exc.code < 600:
                    if attempt < self.max_attempts:
                        time.sleep(2.0 * attempt)
                        continue
                break
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                if attempt < self.max_attempts:
                    time.sleep(2.0 * attempt)
                    continue
                break

        return Completion(text="", model=model, error=last_error or "unknown error")


class FakeProvider:
    """Deterministic answers keyed by the case's user message.

    Used by the test suite and by ``--offline``. Latency is simulated from the answer length,
    and cost is computed from the configured pricing file so the money path is still exercised.

    ``match="exact"`` (default) requires the user message to equal a key. ``match="contains"``
    picks the longest key contained in the message — which is how a scripted *judge* is replayed,
    because the judge prompt wraps the answer in a template.
    """

    name = "fake"

    def __init__(
        self,
        answers: dict[str, str] | None = None,
        pricing: dict | None = None,
        match: str = "exact",
    ) -> None:
        if match not in ("exact", "contains"):
            raise ValueError("match must be 'exact' or 'contains'")
        self.answers = answers or {}
        self.pricing = pricing or {}
        self.match = match

    def _lookup(self, user: str) -> str | None:
        if self.match == "exact":
            return self.answers.get(user)
        hits = [key for key in self.answers if key and key in user]
        if not hits:
            return None
        return self.answers[max(hits, key=len)]

    def complete(self, messages: list[dict], model: str, temperature: float = 0.0) -> Completion:
        user = next(
            (m.get("content", "") for m in reversed(messages) if m.get("role") == "user"), ""
        )
        scripted = self._lookup(user)
        if scripted is None:
            return Completion(
                text="",
                model=model,
                error="FakeProvider has no scripted answer for this input (by design: a missing "
                "fixture must fail loudly, not silently pass)",
            )
        text = scripted
        prompt_tokens = max(1, sum(len(m.get("content", "")) for m in messages) // 4)
        completion_tokens = max(1, len(text) // 4)
        return Completion(
            text=text,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=5 + completion_tokens // 2,
            attempts=1,
            cost_usd=cost_usd(self.pricing, model, prompt_tokens, completion_tokens),
        )
