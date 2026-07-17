import logging

import httpx

from mdm import config

logger = logging.getLogger(__name__)


class OllamaClient:
    def check(self) -> bool:
        base_url = config.get_ollama_base_url()
        model = config.get_ollama_ready_model()
        try:
            response = httpx.post(
                f"{base_url}/api/generate",
                json={
                    "model": model,
                    "prompt": "ping",
                    "stream": False,
                    "options": {"num_predict": 1},
                },
                timeout=10.0,
            )
            if response.status_code != 200:
                logger.warning(
                    "Ollama readiness check got non-200 status %s from %s (model=%s)",
                    response.status_code,
                    base_url,
                    model,
                )
            return response.status_code == 200
        except httpx.HTTPError as exc:
            logger.warning(
                "Ollama readiness check failed against %s (model=%s): %s",
                base_url,
                model,
                exc,
            )
            return False
