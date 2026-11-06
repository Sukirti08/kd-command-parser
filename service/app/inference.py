"""Prompt format and generation shared by training, evaluation and the service.

torch/transformers are imported lazily so the web layer and the unit tests can
run without them.
"""
from __future__ import annotations

PROMPT_TEMPLATE = "Command: {text}\nJSON:"


def build_prompt(text: str) -> str:
    return PROMPT_TEMPLATE.format(text=text.strip())


def build_example(text: str, target: str) -> tuple[str, str]:
    """(prompt, completion) pair used for training: the completion starts with a space."""
    return build_prompt(text), " " + target


def object_end(generated: str) -> int | None:
    """Index just past the first complete top-level JSON object, or None."""
    depth, in_str, esc = 0, False, False
    start = generated.find("{")
    if start < 0:
        return None
    for i in range(start, len(generated)):
        c = generated[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i + 1
    return None


def trim_after_object(generated: str) -> str:
    """Stop condition of generation: keep text up to the end of the first object.

    Leading whitespace is dropped and anything generated after the closing brace
    is discarded. If no complete object exists the text is returned unchanged
    (stripped) and will fail validation, exactly as score.py would see it.
    """
    end = object_end(generated)
    return generated[:end].strip() if end is not None else generated.strip()


class Generator:
    """Greedy decoder around a causal LM, stopping at the end of the JSON object."""

    def __init__(self, model_dir: str, max_new_tokens: int = 48, threads: int | None = None):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        if threads:
            torch.set_num_threads(threads)
        self.torch = torch
        self.tok = AutoTokenizer.from_pretrained(model_dir)
        if self.tok.pad_token is None:
            self.tok.pad_token = self.tok.eos_token
        self.model = AutoModelForCausalLM.from_pretrained(model_dir, torch_dtype=torch.float32)
        self.model.eval()
        self.max_new_tokens = max_new_tokens
        self._stop = self._make_stopper()

    def _make_stopper(self):
        from transformers import StoppingCriteria, StoppingCriteriaList

        tok, outer = self.tok, self

        class StopOnObject(StoppingCriteria):
            def __call__(self, input_ids, scores, **kwargs):
                new = tok.decode(input_ids[0, outer._prompt_len:], skip_special_tokens=True)
                return object_end(new) is not None

        return StoppingCriteriaList([StopOnObject()])

    def generate(self, text: str) -> str:
        enc = self.tok(build_prompt(text), return_tensors="pt")
        self._prompt_len = enc["input_ids"].shape[1]
        with self.torch.no_grad():
            out = self.model.generate(
                **enc,
                max_new_tokens=self.max_new_tokens,
                do_sample=False,
                num_beams=1,
                pad_token_id=self.tok.pad_token_id,
                eos_token_id=self.tok.eos_token_id,
                stopping_criteria=self._stop,
            )
        new = self.tok.decode(out[0, self._prompt_len:], skip_special_tokens=True)
        return trim_after_object(new)
