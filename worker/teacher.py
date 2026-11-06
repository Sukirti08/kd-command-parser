"""Teacher client: Phi-3.5-mini-instruct served by Ollama, temperature 0, seed 42."""
from __future__ import annotations

import os
import time
from pathlib import Path

import requests

TEACHER_MODEL = os.environ.get("TEACHER_MODEL", "phi3.5")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
NUM_PREDICT = int(os.environ.get("TEACHER_NUM_PREDICT", "64"))
DEFAULT_PROMPT = Path(__file__).resolve().parent.parent / "prompts" / "teacher_prompt.txt"


def load_prompt(path: str | os.PathLike | None = None) -> str:
    return Path(path or os.environ.get("PROMPT_FILE", DEFAULT_PROMPT)).read_text(encoding="utf-8")


def render(template: str, command: str) -> str:
    # str.replace, not str.format: the prompt contains literal JSON braces.
    return template.replace("{command}", command)


def options() -> dict:
    """Fixed by the assignment for every student: temperature 0, seed 42."""
    return {"temperature": 0, "seed": 42, "num_predict": NUM_PREDICT, "stop": ["\nCommand", "\n\n"]}


def ask(template: str, command: str, retries: int = 5, timeout: int = 600) -> str:
    """Return the teacher's reply exactly as generated (no stripping, no editing)."""
    body = {
        "model": TEACHER_MODEL,
        "prompt": render(template, command),
        "stream": False,
        "options": options(),
    }
    for attempt in range(retries):
        try:
            r = requests.post(f"{OLLAMA_URL}/api/generate", json=body, timeout=timeout)
            r.raise_for_status()
            return r.json()["response"]
        except (requests.RequestException, KeyError):
            if attempt == retries - 1:
                raise
            time.sleep(2 ** attempt)
    raise RuntimeError("unreachable")
