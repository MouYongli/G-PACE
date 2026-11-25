"""The paper's surface renderer: a model no evaluated system uses (design section 7; D006).

D006 chose Mistral-Small-3.2-24B-Instruct-2506 (`configs/models/mistral-small-3.2-24b.yaml`),
served locally through `envs/serve` (`scripts/serve-model.sh` with the flags of the model config).
`ModelRenderer` implements the `Renderer` interface of `render.py`:

- one chat call per attempt through `grace.llm.client.ChatClient` (call type `render`, trigger
  `write`, history ID = sequence ID, version = message version), with the pinned prompt
  `render-changeseq` and the decoding of the model config; the seed is `request.seed + attempt`
  (mod 2**31), so every attempt of every message has its own fixed seed;
- the user message carries what section 7 lists: speaker, persona and register, the episode date,
  the previous six rendered messages (never later ones), the message's events as fact lines and
  its meaning as the template sentence, the discourse requirement, the required, allowed and
  forbidden mentions; a filler gets "small talk" as its topic;
- `render_messages` (in `render.py`) checks every attempt, retries up to three times and falls
  back to the template sentence; `question` keeps the template question text.

Token counting: the snapshot is in Mistral format (tekken.json, no Jinja chat template), and the
server encodes prompts with mistral-common. `TekkenCounter` counts the same Tekken v11 format
locally (`<s>[SYSTEM_PROMPT]...[/SYSTEM_PROMPT][INST]...[/INST]`) with the tokenizer converted by
transformers, so the research environment does not need mistral-common. Every call compares the
local count with the server's `prompt_tokens`; `ModelRenderer.token_check()` reports the result.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml

from grace.config.paths import REPO_ROOT
from grace.eval.datasets.changeseq.generate import render_date
from grace.eval.datasets.changeseq.render import RenderRequest, question_text, template_sentence
from grace.llm.client import ChatClient, Endpoint
from grace.llm.prompts import Prompt, load_pinned
from grace.llm.records import CallContext, CallLedger
from grace.llm.tokens import (
    Message,
    TokenizerPin,
    TokenizerPinError,
    locate_snapshot,
    verify_snapshot,
)

PROMPT_REGISTRY = REPO_ROOT / "configs" / "common" / "prompts.yaml"
DEFAULT_MODEL_CONFIG = REPO_ROOT / "configs" / "models" / "mistral-small-3.2-24b.yaml"
DISCOURSE = {"correction": "must signal that an earlier statement was wrong",
             "change": "must signal that the state changed"}
_LABEL = re.compile(r"^\s*(user|assistant)\s*:\s*", re.IGNORECASE)


class TekkenCounter:
    """Token counter for a Mistral Tekken v11 snapshot (system, user and assistant turns)."""

    BOS, SYS, SYS_END, INST, INST_END, EOS = 1, 1, 1, 1, 1, 1   # one control token each

    def __init__(self, pin: TokenizerPin, snapshot: Path):
        verify_snapshot(pin, snapshot)
        if pin.chat_template != "tekken.json":
            raise TokenizerPinError(f"{pin.model}: TekkenCounter needs the tekken.json pin")
        from transformers.integrations.mistral import MistralConverter

        self.pin = pin
        self.name = f"{pin.hf_repo}@{pin.revision}"
        converter = MistralConverter(vocab_file=str(snapshot / "tekken.json"),
                                     add_prefix_space=False)
        self._tokenizer = converter.converted()

    @classmethod
    def from_model_config(cls, path: Path) -> TekkenCounter:
        pin = TokenizerPin.from_file(path)
        return cls(pin, locate_snapshot(pin))

    def count_text(self, text: str) -> int:
        return len(self._tokenizer.encode(text, add_special_tokens=False).ids)

    def count_messages(self, messages: Sequence[Message]) -> int:
        roles = [m["role"] for m in messages]
        if "system" in roles[1:]:
            raise ValueError("Tekken v11: a system message must come first")
        total = self.BOS
        for m in messages:
            n = self.count_text(m["content"])
            if m["role"] == "system":
                total += self.SYS + n + self.SYS_END
            elif m["role"] == "user":
                total += self.INST + n + self.INST_END
            elif m["role"] == "assistant":
                total += n + self.EOS
            else:
                raise ValueError(f"Tekken v11: unsupported role {m['role']!r}")
        return total


def clean(text: str | None) -> str:
    """The message text of a reply: whitespace, one pair of enclosing quotes and a speaker label
    removed."""
    def unquote(s: str) -> str:
        if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
            return s[1:-1].strip()
        return s

    text = unquote((text or "").strip())
    return unquote(_LABEL.sub("", text, count=1).strip())


def prompt_values(request: RenderRequest) -> dict[str, str]:
    """The variables of the `render-changeseq` prompt for one message."""
    if request.skeleton == "filler":
        meaning = (f"{request.topic or 'small talk'}: a short conversational turn like "
                   f"\"{template_sentence(request)}\"")
        facts = ("none: small talk that touches no booking, person, place, date, time, language "
                 "or hobby, and refers to no detail of the earlier messages")
    else:
        meaning = template_sentence(request)
        facts = "; ".join(request.facts) or "none"
    return {
        "speaker": request.speaker, "persona": request.persona, "register": request.register,
        "date": render_date(request.date),
        "previous": "\n".join(request.previous) or "(none, this is the first message)",
        "meaning": meaning, "facts": facts,
        "discourse": DISCOURSE.get(request.discourse or "", "none"),
        "required": "; ".join(request.required) or "nothing",
        "allowed": "; ".join(request.allowed) or "nothing",
        "forbidden": "; ".join(request.forbidden) or "nothing",
    }


class ModelRenderer:
    """`Renderer` that sends one chat call per attempt through `grace.llm`."""

    kind = "model"

    def __init__(self, client: ChatClient, prompt: Prompt, model_config: Mapping[str, Any],
                 model_config_path: str):
        self.client, self.prompt = client, prompt
        self.config = dict(model_config)
        self.config_path = model_config_path
        self.name = f"{model_config['hf_repo']}@{model_config['revision']}"
        self.snapshot = model_config["revision"]
        self.decoding = {k: v for k, v in model_config["decoding"].items() if k != "seed"}
        self._lock = threading.Lock()
        self._counts: list[tuple[int, int | None]] = []   # (local, server) per call

    def render(self, request: RenderRequest, attempt: int) -> str:
        messages = self.prompt.render(**prompt_values(request))
        decoding = {**self.decoding, "seed": (request.seed + attempt) % 2**31}
        context = CallContext("render", "write", history_id=request.sequence_id,
                              version=request.version)
        result = self.client.chat(messages, context, prompt_sha256=self.prompt.sha256,
                                  decoding=decoding)
        with self._lock:
            self._counts.append((result.records[-1].input_tokens, result.server_input_tokens))
        return clean(result.text)

    def question(self, spec: Mapping[str, Any]) -> str:
        return question_text(spec)

    def token_check(self) -> dict[str, Any]:
        """Local input-token counts against the server's prompt_tokens."""
        with self._lock:
            counts = list(self._counts)
        reported = [(a, b) for a, b in counts if b is not None]
        return {"calls": len(counts), "server_reported": len(reported),
                "mismatches": sum(1 for a, b in reported if a != b),
                "max_abs_difference": max((abs(a - b) for a, b in reported), default=0)}

    def describe(self) -> dict[str, Any]:
        """Renderer record of `meta.json` and `dataset.json` (the dataset manifest)."""
        return {"name": self.name, "kind": self.kind, "snapshot": self.snapshot,
                "model": self.config["model"], "hf_repo": self.config["hf_repo"],
                "revision": self.config["revision"], "licence": self.config.get("licence"),
                "model_config": self.config_path,
                "tokenizer_files": dict(self.config["tokenizer"]["files"]),
                "prompt": self.prompt.name, "prompt_sha256": self.prompt.sha256,
                "decoding": {**self.decoding, "seed": "request seed + attempt"},
                "serve_args": list(self.config.get("serve", {}).get("args", []))}


def model_renderer(settings: Mapping[str, Any], base_url: str, ledger: CallLedger,
                   max_attempts: int = 3) -> ModelRenderer:
    """Build the model renderer of a dataset config's `renderer` mapping (`kind: model`)."""
    rel = settings.get("model_config", "configs/models/mistral-small-3.2-24b.yaml")
    path = REPO_ROOT / rel
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    pin = TokenizerPin.from_config(config)
    counter = TekkenCounter(pin, locate_snapshot(pin))
    endpoint = Endpoint.for_model(pin, base_url, config["served_name"])
    client = ChatClient(endpoint, ledger, counter, max_attempts=max_attempts)
    prompt = load_pinned(settings.get("prompt", "render-changeseq"), PROMPT_REGISTRY)
    return ModelRenderer(client, prompt, config, rel)
