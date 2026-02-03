from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class LlmResponse:
    text: str
    model: str | None


class LlmMcp(Protocol):
    def generate(
        self, model: str, prompt: str, temperature: float = 0.2, system: str | None = None
    ) -> LlmResponse: ...


class OllamaMcp:
    def __init__(self, base_url: str, timeout_seconds: int = 600):
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds

    def tags(self) -> list[str]:
        url = f"{self._base_url}/api/tags"
        req = urllib.request.Request(url, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            msg = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"ollama http error {e.code}: {msg}") from e
        except Exception as e:
            raise RuntimeError(f"ollama request failed: {e}") from e
        models = payload.get("models") or []
        out: list[str] = []
        for m in models:
            name = m.get("name") or m.get("model")
            if name:
                out.append(str(name))
        return out

    def generate(
        self, model: str, prompt: str, temperature: float = 0.2, system: str | None = None
    ) -> LlmResponse:
        url = f"{self._base_url}/api/generate"
        body = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": temperature},
        }
        if system:
            body["system"] = system
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url, data=data, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            msg = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"ollama http error {e.code}: {msg}") from e
        except Exception as e:
            raise RuntimeError(f"ollama request failed: {e}") from e
        return LlmResponse(
            text=str(payload.get("response", "")), model=payload.get("model")
        )


class LmStudioMcp:
    """LM Studio provides an OpenAI-compatible API."""

    def __init__(self, base_url: str, timeout_seconds: int = 600):
        # base_url should be like http://localhost:1234/v1
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds

    def generate(
        self, model: str, prompt: str, temperature: float = 0.2, system: str | None = None
    ) -> LlmResponse:
        url = f"{self._base_url}/chat/completions"
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        body = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
        }
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url, data=data, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            msg = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"lm-studio http error {e.code}: {msg}") from e
        except Exception as e:
            raise RuntimeError(f"lm-studio request failed: {e}") from e

        choices = payload.get("choices") or []
        if not choices:
            raise RuntimeError("lm-studio returned no choices")

        text = choices[0].get("message", {}).get("content", "")
        return LlmResponse(text=str(text), model=payload.get("model"))


def normalize_model_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", name.lower())


def suggest_model(preferred: str, available: list[str]) -> str | None:
    pref_norm = normalize_model_name(preferred)
    if not available:
        return None
    for m in available:
        if normalize_model_name(m) == pref_norm:
            return m
    candidates = [
        preferred,
        preferred + ":latest" if ":" not in preferred else preferred,
        preferred.replace("tranlate", "translate"),
        preferred.replace("tranlategemma", "translategemma"),
        preferred.replace("translate-gemma", "translategemma"),
        preferred.replace("translategemma", "translategemma:latest"),
    ]
    candidates = [c for c in candidates if c and c != preferred]
    for c in candidates:
        c_norm = normalize_model_name(c)
        for m in available:
            if normalize_model_name(m) == c_norm:
                return m
    for m in available:
        if "translategemma" in normalize_model_name(m):
            return m
    return None


def resolve_llm_model(mcp: LlmMcp, preferred: str) -> str:
    if isinstance(mcp, OllamaMcp):
        try:
            available = mcp.tags()
            return suggest_model(preferred, available) or preferred
        except Exception:
            return preferred
    # LM Studio might not have an easy tags/models API that we want to depend on
    # or it might be different. For now, just return preferred for LM Studio.
    return preferred


def build_llm_mcp(provider: str, base_url: str, timeout_seconds: int = 120) -> LlmMcp:
    p = provider.lower()
    if p == "ollama":
        return OllamaMcp(base_url, timeout_seconds)
    if p in ("lm-studio", "lmstudio", "openai"):
        return LmStudioMcp(base_url, timeout_seconds)
    raise ValueError(f"unsupported llm provider: {provider}")
