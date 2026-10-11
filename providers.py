"""Model adapters. Credentials stay in environment/.env, never in output bundles."""
import json
import os
from urllib.parse import urlsplit

import requests

PROVIDERS = {
    "openai": {"label": "ChatGPT / OpenAI", "base": "https://api.openai.com/v1", "model": "gpt-4.1-mini", "key": "OPENAI_API_KEY"},
    "gemini": {"label": "Google Gemini", "base": "https://generativelanguage.googleapis.com/v1beta/openai", "model": "gemini-3.8-flash", "key": "GEMINI_API_KEY"},
    "deepseek": {"label": "DeepSeek", "base": "https://api.deepseek.com/v1", "model": "deepseek-chat", "key": "DEEPSEEK_API_KEY"},
    "claude": {"label": "Anthropic Claude", "base": "https://api.anthropic.com/v1", "model": "", "key": "ANTHROPIC_API_KEY"},
    "custom": {"label": "Custom OpenAI-compatible", "base": "", "model": "", "key": "LLM_API_KEY"},
}


def settings():
    name = os.getenv("LLM_PROVIDER", "deepseek").strip().lower()
    if name not in PROVIDERS:
        raise ValueError("LLM_PROVIDER must be openai/gemini/deepseek/claude/custom.")
    preset = PROVIDERS[name]
    return {"provider": name,
            "base": (os.getenv("LLM_BASE_URL") or os.getenv(name.upper() + "_BASE_URL") or preset["base"]).rstrip("/"),
            "model": os.getenv("LLM_MODEL") or os.getenv(name.upper() + "_MODEL") or preset["model"],
            "key": os.getenv(preset["key"]) or os.getenv("LLM_API_KEY", "")}


def configured():
    cfg = settings()
    return bool(cfg["key"] and cfg["model"] and cfg["base"])


def complete(system, user):
    cfg = settings()
    if not cfg["key"] or not cfg["model"]:
        raise ValueError("Configure an API key and model ID for the selected provider.")
    url = urlsplit(cfg["base"])
    if url.username or url.password or url.query or url.fragment or not url.hostname:
        raise ValueError("The model base URL must not contain credentials, query or fragment.")
    if url.scheme != "https" and not (url.scheme == "http" and url.hostname in ("127.0.0.1", "localhost", "::1")):
        raise ValueError("Model endpoints require HTTPS, except loopback HTTP.")
    if cfg["provider"] == "claude":
        endpoint = "/messages"
        headers = {"x-api-key": cfg["key"], "anthropic-version": "2023-06-01"}
        payload = {"model": cfg["model"], "max_tokens": 8192, "system": system,
                   "messages": [{"role": "user", "content": user}]}
    else:
        endpoint = "/chat/completions"
        headers = {"Authorization": "Bearer " + cfg["key"]}
        payload = {"model": cfg["model"], "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    try:
        response = requests.post(cfg["base"] + endpoint, headers=headers, json=payload, timeout=240, allow_redirects=False)
        if response.status_code != 200:
            raise RuntimeError(f"{cfg['provider']} API HTTP {response.status_code}; check local configuration.")
        data = response.json()
        if cfg["provider"] == "claude":
            if data.get("stop_reason") == "max_tokens":
                raise ValueError("Model output was truncated; increase the output limit or shorten the source.")
            text = "".join(block["text"] for block in data["content"] if block.get("type") == "text")
        else:
            choice = data["choices"][0]
            if choice.get("finish_reason") == "length":
                raise ValueError("Model output was truncated; choose a model with a larger output limit.")
            text = choice["message"]["content"]
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Model returned no text.")
        return text.strip()
    except requests.RequestException:
        raise RuntimeError("Model request failed; credentials and response bodies are omitted.") from None
    except (KeyError, IndexError, TypeError, json.JSONDecodeError):
        raise ValueError("Model response format is invalid.") from None
