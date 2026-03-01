import os
import time
from typing import Dict, Tuple

from logger import logger
from config import config

try:
    from llama_cpp import Llama
except ImportError:
    Llama = None


class LocalLlmAgent:
    def __init__(self, model_path: str, model_name: str, temperature: float, max_tokens: int):
        self.model_path = model_path
        self.model_id = model_name or os.path.basename(model_path) or "local-llm"
        self.temperature = float(temperature or 0.1)
        self.max_tokens = int(max_tokens or 200)
        self._client = None
        self._load()

    def _load(self):
        if not Llama or not self.model_path:
            logger.debug("Local LLM disabled: missing llama_cpp or model path")
            return
        try:
            self._client = Llama(
                model_path=self.model_path,
                n_ctx=2048,
                temperature=self.temperature,
            )
        except Exception as err:
            logger.warning("Local LLM fail to load %s: %s", self.model_path, err)
            self._client = None

    def ready(self) -> bool:
        return self._client is not None

    def complete(self, prompt: str) -> Tuple[str, Dict[str, int]]:
        if not self.ready():
            return "", {}
        start = time.time()
        try:
            resp = self._client(prompt, max_tokens=self.max_tokens, stop=["\n\n"])
            text = (resp.get("choices") or [{}])[0].get("text", "")
            usage = resp.get("usage", {})
            latency = int((time.time() - start) * 1000)
            logger.info(
                "Local LLM req model=%s tokens=%s latency_ms=%s",
                self.model_id,
                usage.get("total_tokens"),
                latency,
            )
            return text.strip(), usage
        except Exception as err:
            logger.warning("Local LLM completion failed: %s", err)
            return "", {}


_LOCAL_AGENT = None


def get_local_llm_agent() -> LocalLlmAgent:
    global _LOCAL_AGENT
    if _LOCAL_AGENT is not None:
        return _LOCAL_AGENT
    if not config.LOCAL_LLM_ENABLED or not config.LOCAL_LLM_MODEL_PATH:
        return None
    _LOCAL_AGENT = LocalLlmAgent(
        model_path=config.LOCAL_LLM_MODEL_PATH,
        model_name=config.LOCAL_LLM_MODEL_NAME,
        temperature=config.LOCAL_LLM_TEMPERATURE,
        max_tokens=config.LOCAL_LLM_MAX_TOKENS,
    )
    return _LOCAL_AGENT
