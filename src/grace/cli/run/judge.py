"""The `judge` stage (contracts.md, "Experiment run"): one run per upstream `system` run.

A judge run reads the predictions of exactly one completed `system` run and the gold of its
benchmark, judges every `answer` prediction of a question read with one judge
(`grace.eval.analysis.judging.judge`), and writes `calls.jsonl` and `judgements.jsonl`. `unknown`
and `invalid` predictions and state reads are scored by rule and are not judged. Every call goes
through `grace.llm.client.ChatClient`.

Remote judges (the Azure comparison judge of decision D006) have no local tokenizer, so
`input_tokens` in `calls.jsonl` is the count of a local proxy counter (named in
`resolved-config.yaml`), as the client requires; what the server reports (`usage`) is kept per
judgement in `judge-usage.jsonl`, and spend is computed from it:

- `read_id`, `call_id`: the judgement and the call attempt that produced it (the last one);
- `prompt_tokens`, `cached_tokens`, `completion_tokens`: server `usage`, null when the last
  attempt failed;
- `finish_reason`, `server_model`: from the server reply (`content_filter` marks a filtered
  output);
- `http_status`, `error_code`, `error`: of a failed last attempt (`content_filter` marks a
  filtered prompt).

A judgement whose call failed or was filtered has verdict `invalid` (it leaves the denominator as
`n_judge_invalid`); the cause is in `judge-usage.jsonl`. The run fails at once on an
authentication error, after `max_consecutive_failures` failed calls in a row, or when the spend
guard projects or reaches its cap.
"""

from __future__ import annotations

import json
import os
import shlex
import sys
import threading
import time
import traceback
import urllib.error
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import FIRST_EXCEPTION, ThreadPoolExecutor, wait
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from grace.config.paths import project_root
from grace.eval.analysis.judging.judge import Judge, Judgement, write_judgements
from grace.eval.runner.harness import rundir
from grace.llm.client import ChatClient, Endpoint, LLMCallFailed, http_post
from grace.llm.tokens import Message, TokenCounter

USAGE_FILE = "judge-usage.jsonl"
AUTH_STATUSES = (401, 403)


class JudgeAbort(RuntimeError):
    """The judge stage must stop (authentication, repeated failures, spend cap)."""


# ---------------------------------------------------------------------------------------------
# Endpoint, transport and counter


def remote_endpoint(spec: Mapping[str, Any], environ: Mapping[str, str] = os.environ,
                    timeout_s: float = 60.0) -> Endpoint:
    """Endpoint of a remote judge model block of a judge config (`provider: azure-openai`).
    The base URL and deployment are read from the environment variables the block names; the
    key stays in its variable and is read by the client per call."""
    if spec.get("provider") != "azure-openai":
        raise ValueError(f"remote_endpoint serves azure-openai judges, "
                         f"not {spec.get('provider')!r}")
    missing = [spec[k] for k in ("base_url_env", "deployment_env", "api_key_env")
               if not environ.get(spec[k])]
    if missing:
        raise RuntimeError(f"environment variables not set: {', '.join(missing)}")
    return Endpoint(base_url=environ[spec["base_url_env"]],
                    served_model=environ[spec["deployment_env"]],
                    model_label=f"{spec['model']}@{spec['version']}",
                    api_key_env=spec["api_key_env"], auth_header=spec["auth_header"],
                    timeout_s=timeout_s)


class UsageTransport:
    """Wraps the client's HTTP transport and keeps, per thread, what the server said about the
    last attempt: `usage`, finish reason and model, or the HTTP status and error code. A 429
    reply waits (Retry-After, at most `max_wait_s`) before the client's own retry."""

    def __init__(self, post: Callable[[str, dict, dict, float], dict] = http_post,
                 sleep: Callable[[float], None] = time.sleep, max_wait_s: float = 60.0,
                 default_wait_s: float = 10.0):
        self._post, self._sleep = post, sleep
        self.max_wait_s, self.default_wait_s = max_wait_s, default_wait_s
        self._local = threading.local()

    def __call__(self, url: str, payload: dict, headers: dict, timeout: float) -> dict:
        self._local.last = None
        try:
            body = self._post(url, payload, headers, timeout)
        except urllib.error.HTTPError as exc:
            code = _error_code(exc)
            self._local.last = {"http_status": exc.code, "error_code": code}
            if exc.code == 429:
                self._sleep(min(self.max_wait_s, _retry_after(exc, self.default_wait_s)))
            raise OSError(f"HTTP {exc.code} ({code})") from None
        choice = (body.get("choices") or [{}])[0]
        usage = body.get("usage") or {}
        details = usage.get("prompt_tokens_details") or {}
        self._local.last = {"prompt_tokens": usage.get("prompt_tokens"),
                            "cached_tokens": details.get("cached_tokens"),
                            "completion_tokens": usage.get("completion_tokens"),
                            "finish_reason": choice.get("finish_reason"),
                            "server_model": body.get("model")}
        return body

    def take(self) -> dict | None:
        last, self._local.last = getattr(self._local, "last", None), None
        return last


def _error_code(exc: urllib.error.HTTPError) -> str | None:
    try:
        body = json.loads(exc.read().decode("utf-8"))
    except (OSError, ValueError, AttributeError):
        return None
    error = body.get("error") if isinstance(body, dict) else None
    if not isinstance(error, dict):
        return None
    inner = error.get("innererror") or {}
    return str(error.get("code") or inner.get("code") or error.get("type") or "") or None


def _retry_after(exc: urllib.error.HTTPError, default: float) -> float:
    try:
        return float(exc.headers.get("Retry-After"))
    except (TypeError, ValueError, AttributeError):
        return default


class LockedCounter:
    """A token counter shared by worker threads, one count at a time."""

    def __init__(self, counter: TokenCounter):
        self._counter, self._lock = counter, threading.Lock()
        self.name = counter.name

    def count_text(self, text: str) -> int:
        with self._lock:
            return self._counter.count_text(text)

    def count_messages(self, messages: Sequence[Message]) -> int:
        with self._lock:
            return self._counter.count_messages(messages)


# ---------------------------------------------------------------------------------------------
# Spend


def usd(row: Mapping[str, Any], prices: Mapping[str, float]) -> float:
    """Spend of one judgement from server usage; prices in USD per million tokens
    (`input`, `cached_input`, `output`)."""
    prompt = row.get("prompt_tokens") or 0
    cached = min(row.get("cached_tokens") or 0, prompt)
    out = row.get("completion_tokens") or 0
    return ((prompt - cached) * prices["input"] + cached * prices["cached_input"]
            + out * prices["output"]) / 1e6


class SpendGuard:
    """Running spend over all judge runs of one invocation. After `check_after` (a fraction) of
    the planned calls, the projected total must stay within `cap_usd`; the spend itself always
    must."""

    def __init__(self, cap_usd: float, planned_calls: int, prices: Mapping[str, float],
                 check_after: float = 0.1):
        self.cap_usd, self.planned, self.prices = cap_usd, planned_calls, dict(prices)
        self.check_after = check_after
        self.spent, self.calls = 0.0, 0
        self._lock = threading.Lock()

    def add(self, row: Mapping[str, Any]) -> None:
        with self._lock:
            self.spent += usd(row, self.prices)
            self.calls += 1
            if self.spent > self.cap_usd:
                raise JudgeAbort(f"spend cap reached: USD {self.spent:.4f} > {self.cap_usd}")
            if self.planned and self.calls >= max(1, self.check_after * self.planned):
                projected = self.spent / self.calls * self.planned
                if projected > self.cap_usd:
                    raise JudgeAbort(f"projected spend USD {projected:.4f} exceeds the cap "
                                     f"{self.cap_usd} after {self.calls} calls")


# ---------------------------------------------------------------------------------------------
# Stage


def judgeable(predictions: Sequence[Mapping[str, Any]], tasks: Mapping[str, Mapping[str, Any]]
              ) -> list[Mapping[str, Any]]:
    """`answer` predictions of question reads, in file order."""
    return [p for p in predictions if p["output"] == "answer"
            and tasks.get(p["read_id"], {}).get("kind") == "question"]


@dataclass
class JudgeRun:
    run_dir: Path
    run_id: str
    status: str
    failure: str | None
    n_judgements: int


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines()
            if line.strip()]


def run_judge(upstream_dir: Path, *, run_root: Path, experiment: str, judge_name: str,
              make_judge: Callable[[ChatClient], Judge],
              make_client: Callable[[Any], ChatClient], usage: UsageTransport,
              tasks: Mapping[str, Mapping[str, Any]], gold: Mapping[str, Mapping[str, Any]],
              data: list[dict[str, Any]], resolved: Mapping[str, Any], config_path: str,
              seed: int = 0, workers: int = 4, guard: SpendGuard | None = None,
              limit: int | None = None, max_consecutive_failures: int = 5,
              code: rundir.CodeState | None = None, command: str | None = None,
              device: str = "cpu (remote judge API)") -> JudgeRun | None:
    """One judge run over one completed upstream run; None when it has nothing to judge.

    `tasks` maps read_id to read-task records and `gold` maps task_id to the gold record of the
    scored annotation; `make_client(ledger)` builds the client (with `usage` as its transport)."""
    from grace.llm.records import CallLedger

    upstream_dir = Path(upstream_dir)
    upstream = json.loads((upstream_dir / "run.json").read_text(encoding="utf-8"))
    if upstream["stage"] not in ("system", "read") or upstream["status"] != "completed":
        raise ValueError(f"{upstream['run_id']}: upstream must be a completed system or read run")
    predictions = read_jsonl(upstream_dir / "predictions.jsonl")
    todo = judgeable(predictions, tasks)
    if limit is not None:
        todo = todo[:limit]
    if not todo:
        return None
    for p in todo:
        if p["task_id"] not in gold:
            raise ValueError(f"{p['read_id']}: no gold for task {p['task_id']}")
    code = code or rundir.code_state()
    run_dir = rundir.create(run_root, experiment)
    run_id = run_dir.name
    full = {**resolved, "stage": "judge", "experiment": experiment, "judge": judge_name,
            "upstream_run": upstream["run_id"], "workers": workers, "limit": limit,
            "judgeable_predictions": len(todo)}
    (run_dir / "resolved-config.yaml").write_text(
        yaml.safe_dump(full, sort_keys=True, allow_unicode=True), encoding="utf-8")
    run = rundir.RunJson(run_dir, {
        "run_id": run_id, "experiment": experiment, "stage": "judge",
        "upstream": [{"run_id": upstream["run_id"], "stage": upstream["stage"],
                      "path": upstream_dir.resolve().as_posix(),
                      "run_json_sha256": rundir.file_sha256(upstream_dir / "run.json")}],
        "code_sha": code.sha, "code_dirty": code.dirty, "config_path": config_path,
        "config_sha256": rundir.file_sha256(run_dir / "resolved-config.yaml"),
        "resources_sha256": rundir.resources_sha256(), "data": data,
        "project_root": project_root().as_posix(), "seed": seed,
        "command": command or " ".join(shlex.quote(a) for a in sys.argv),
        "environment": rundir.environment(device)})
    log = (run_dir / "run.log").open("a", encoding="utf-8")
    ledger = CallLedger(run_dir / "calls.jsonl", run_id)
    ledger.path.touch()
    judge = make_judge(make_client(ledger))
    results: dict[int, tuple[Judgement, dict]] = {}
    state = {"consecutive": 0}
    lock = threading.Lock()

    def one(index: int, prediction: Mapping[str, Any]) -> None:
        task = tasks[prediction["read_id"]]
        try:
            judgement = judge.judge(task, gold[prediction["task_id"]], prediction)
            row = usage.take() or {}
            failed = False
        except LLMCallFailed as exc:
            row = usage.take() or {}
            row.setdefault("error", str(exc))
            judgement = Judgement(read_id=task["read_id"], task_id=task["task_id"],
                                  annotation=gold[prediction["task_id"]]["annotation"],
                                  judge=judge_name, verdict="invalid", raw_output=None,
                                  call_id=exc.records[-1].call_id)
            failed = row.get("error_code") != "content_filter"
            if row.get("http_status") in AUTH_STATUSES:
                raise JudgeAbort(f"authentication failed: HTTP {row['http_status']}") from exc
        row = {"read_id": judgement.read_id, "call_id": judgement.call_id,
               **{k: row.get(k) for k in ("prompt_tokens", "cached_tokens", "completion_tokens",
                                          "finish_reason", "server_model", "http_status",
                                          "error_code", "error")}}
        with lock:
            results[index] = (judgement, row)
            state["consecutive"] = state["consecutive"] + 1 if failed else 0
            if state["consecutive"] >= max_consecutive_failures:
                raise JudgeAbort(f"{state['consecutive']} judge calls failed in a row; "
                                 f"last: {row.get('error')}")
        if guard is not None:
            guard.add(row)

    failure = None
    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(one, i, p) for i, p in enumerate(todo)]
            done, _ = wait(futures, return_when=FIRST_EXCEPTION)
            errors = [f.exception() for f in done if f.exception() is not None]
            if errors:
                for future in futures:
                    future.cancel()
                raise errors[0]
    except Exception as exc:  # noqa: BLE001 - recorded as the run's failure
        failure = f"{type(exc).__name__}: {exc}"
        log.write(traceback.format_exc())
    ordered = [results[i] for i in sorted(results)]
    write_judgements(run_dir / "judgements.jsonl", [j for j, _ in ordered])
    with (run_dir / USAGE_FILE).open("x", encoding="utf-8") as handle:
        for _, row in ordered:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    if failure is None and len(ordered) != len(todo):
        failure = f"record count: {len(ordered)} judgements, {len(todo)} judgeable predictions"
    verdicts = {v: sum(1 for j, _ in ordered if j.verdict == v)
                for v in ("correct", "incorrect", "invalid")}
    log.write(f"{upstream['run_id']}: {len(ordered)} of {len(todo)} judged; {verdicts}; "
              f"{len(ledger.records)} call attempts\n")
    log.close()
    run.finish(len(ordered), failure)
    return JudgeRun(run_dir, run_id, run.data["status"], run.data["failure"], len(ordered))
