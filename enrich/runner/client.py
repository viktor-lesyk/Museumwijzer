"""OpenAI-compatible HTTP API client with exponential backoff and tool calling."""

import json
import logging
import time
from typing import Any, Dict, List, Optional
import requests

logger = logging.getLogger("enrich.client")


class OpenAICompatClient:
    def __init__(
        self,
        base_url: str = "http://localhost:11434/v1",
        api_key: Optional[str] = None,
        max_retries: int = 3,
        timeout: int = 45,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or "not-needed"
        self.max_retries = max_retries
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
            "HTTP-Referer": "https://github.com/museumwijzer/museumwijzer",
            "X-Title": "Museumwijzer Enrichment Runner",
        })

    def _post_with_retry(self, endpoint: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        url = f"{self.base_url}{endpoint}"
        delay = 2.0
        last_error = None

        for attempt in range(self.max_retries + 1):
            try:
                resp = self.session.post(url, json=payload, timeout=self.timeout)
                if resp.status_code == 200:
                    return resp.json()
                elif resp.status_code in (429, 502, 503, 504):
                    logger.warning(
                        f"HTTP {resp.status_code} on {url}. Retrying in {delay:.1f}s (attempt {attempt+1}/{self.max_retries})..."
                    )
                    time.sleep(delay)
                    delay *= 2.0
                    last_error = f"HTTP {resp.status_code}: {resp.text}"
                else:
                    raise RuntimeError(f"API request failed with HTTP {resp.status_code}: {resp.text}")
            except (requests.ConnectionError, requests.Timeout) as e:
                logger.warning(f"Connection error: {e}. Retrying in {delay:.1f}s...")
                time.sleep(delay)
                delay *= 2.0
                last_error = str(e)

        raise RuntimeError(f"Failed after {self.max_retries} retries: {last_error}")

    def chat_completion(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        temperature: float = 0.0,
        json_mode: bool = False,
    ) -> str:
        """Standard chat completion returning text string."""
        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        data = self._post_with_retry("/chat/completions", payload)
        choices = data.get("choices", [])
        if not choices:
            raise RuntimeError(f"No choices returned from LLM: {data}")
        msg = choices[0].get("message", {})
        return msg.get("content", "") or ""

    def chat_with_tools(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        temperature: float = 0.0,
    ) -> Dict[str, Any]:
        """Chat completion returning the message object (content and/or tool_calls)."""
        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
            "temperature": temperature,
        }
        data = self._post_with_retry("/chat/completions", payload)
        choices = data.get("choices", [])
        if not choices:
            raise RuntimeError(f"No choices returned from LLM: {data}")
        return choices[0].get("message", {})
