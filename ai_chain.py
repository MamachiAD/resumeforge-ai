"""Quota-aware text generation: tries each Gemini model, then other free providers, and always moves on fast.
Daily-limit errors skip to the next model at once (no pointless retries); short rate limits wait once; server
errors retry once. Drop-in for the loop inside generate_promo().
"""
import logging
import os
import re
import time
from typing import Callable, List, Optional, Tuple

import requests

logger = logging.getLogger(__name__)

# name, endpoint, env var holding the key, model. All three are free-tier OpenAI-style APIs.
EXTRA_PROVIDERS = [
    ("groq", "https://api.groq.com/openai/v1/chat/completions", "GROQ_API_KEY", os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")),
    ("openrouter", "https://openrouter.ai/api/v1/chat/completions", "OPENROUTER_API_KEY", os.environ.get("OPENROUTER_MODEL", "openrouter/free")),
    ("mistral", "https://api.mistral.ai/v1/chat/completions", "MISTRAL_API_KEY", os.environ.get("MISTRAL_MODEL", "mistral-small-latest")),
]


def classify(err: Exception) -> Tuple[str, float]:
    """Returns (kind, wait_seconds). kind: daily | minute | transient | skip."""
    code = getattr(err, "code", None) or getattr(err, "status_code", None)
    text = str(err)
    wait = 0.0
    m = re.search(r"retry in (?:(\d+)h)?(?:(\d+)m)?(\d+(?:\.\d+)?)s", text)
    if m:
        wait = int(m.group(1) or 0) * 3600 + int(m.group(2) or 0) * 60 + float(m.group(3))
    else:
        m = re.search(r"retryDelay\W+(\d+(?:\.\d+)?)s", text)
        if m:
            wait = float(m.group(1))
    if code == 429 or "RESOURCE_EXHAUSTED" in text:
        if "PerDay" in text or "per day" in text.lower() or wait > 120:
            return "daily", wait
        return "minute", wait or 15
    if code in (400, 401, 403, 404):
        return "skip", 0
    return "transient", 0


class _HttpError(Exception):
    def __init__(self, code, text):
        super().__init__(f"{code} {text[:400]}")
        self.code = code


def _openai_style(url: str, key: str, model: str, prompt: str) -> str:
    r = requests.post(url, headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                      json={"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": 1}, timeout=30)
    if r.status_code != 200:
        err = _HttpError(r.status_code, r.text)
        if r.headers.get("retry-after"):
            err = _HttpError(r.status_code, r.text + f" retry in {r.headers['retry-after']}s")
        raise err
    return r.json()["choices"][0]["message"]["content"]


def ask_text(prompt: str, gemini_call: Callable[[str, str], str], gemini_models: List[str],
             budget_s: float = 120) -> Tuple[Optional[str], Optional[str]]:
    """gemini_call(model, prompt) -> text. Returns (text, provider_used) or (None, None) if everything failed."""
    started = time.time()
    steps = [(f"gemini:{m}", (lambda m=m: gemini_call(m, prompt))) for m in gemini_models]
    for name, url, env, model in EXTRA_PROVIDERS:
        key = os.environ.get(env, "").strip()
        if key:
            steps.append((f"{name}:{model}", (lambda url=url, key=key, model=model: _openai_style(url, key, model, prompt))))
    for label, fn in steps:
        for attempt in (1, 2):
            if time.time() - started > budget_s:
                logger.error("AI time budget used up")
                return None, None
            try:
                text = (fn() or "").strip()
                if text:
                    return text, label
                raise ValueError("empty response")
            except Exception as e:
                kind, wait = classify(e)
                logger.warning("%s attempt %d: %s (%s)", label, attempt, str(e)[:160], kind)
                if kind in ("daily", "skip"):
                    break                                   # nothing to gain by retrying, go to the next one now
                if kind == "minute" and attempt == 1 and wait <= 20:
                    time.sleep(wait + 1); continue          # a short rate limit: wait it out once
                if kind == "transient" and attempt == 1:
                    time.sleep(3); continue                 # server hiccup: one quick retry
                break
    return None, None
