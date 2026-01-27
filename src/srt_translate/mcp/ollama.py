from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass


@dataclass(frozen=True)
class OllamaResponse:
    text: str
    model: str | None


class OllamaMcp:
    def __init__(self, base_url: str, timeout_seconds: int = 120):
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

    def generate(self, model: str, prompt: str, temperature: float = 0.2, system: str | None = None) -> OllamaResponse:
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
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            msg = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"ollama http error {e.code}: {msg}") from e
        except Exception as e:
            raise RuntimeError(f"ollama request failed: {e}") from e
        return OllamaResponse(text=str(payload.get("response", "")), model=payload.get("model"))


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


def resolve_ollama_model(ollama: OllamaMcp, preferred: str) -> str:
    try:
        available = ollama.tags()
    except Exception:
        return preferred
    return suggest_model(preferred, available) or preferred
