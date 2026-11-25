"""Synthetic source files in the formats of the real benchmark releases (task T002).

`build(slug, root)` writes a tiny, made-up release of one benchmark under
`root/data/<slug>/<version>/` with its `MANIFEST.sha256`, and returns a `BenchmarkConfig` bound to
it. No benchmark text is copied; every string is invented. Each source carries the features its
adapter must handle: excluded inputs, masked fields, unresolvable evidence, duplicate session IDs,
empty turns. `SENTINEL` marks every value that must never reach a visible record.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from grace.eval.datasets.benchmarks.base import BenchmarkConfig

SENTINEL = "GOLDSENTINEL"


def _write(directory: Path, files: dict[str, str | bytes]) -> str:
    """Write the files and their MANIFEST.sha256; return the manifest's SHA-256."""
    lines = []
    for name, content in sorted(files.items()):
        path = directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        data = content.encode("utf-8") if isinstance(content, str) else content
        path.write_bytes(data)
        lines.append(f"{hashlib.sha256(data).hexdigest()}  {name}\n")
    manifest = "".join(lines).encode("utf-8")
    (directory / "MANIFEST.sha256").write_bytes(manifest)
    return hashlib.sha256(manifest).hexdigest()


def _config(slug: str, version: str, sha: str, splits: dict, adapter: dict | None = None,
            extra: dict | None = None) -> BenchmarkConfig:
    return BenchmarkConfig.from_dict({
        "benchmark": slug, "version": version, "data_root": f"data/{slug}",
        "manifest_sha256": sha, "extra_manifests": extra or {}, "splits": splits,
        "adapter": adapter or {}})


def locomo(root: Path) -> BenchmarkConfig:
    def turn(dia, speaker, text, **extra):
        return {"speaker": speaker, "dia_id": dia, "text": text, **extra}

    conv = {
        "speaker_a": "Mel", "speaker_b": "Caro",
        "session_1_date_time": "1:56 pm on 8 May, 2023",
        "session_1": [turn("D1:1", "Mel", "I started violin lessons."),
                      turn("D1:2", "Caro", "Look at my cat Pip!", img_url=["http://x/y.jpg"],
                           blip_caption=f"a photo of a cat {SENTINEL}", query="cat")],
        "session_2_date_time": "10:00 am on 28 August, 2023",
        "session_2": [turn("D2:1", "Mel", "I picked up the clarinet.")],
        "session_3_date_time": "9:00 am on 1 September, 2023",
    }
    qa = [
        {"question": "Which instruments does Mel play?", "answer": f"violin, clarinet {SENTINEL}",
         "evidence": ["D1:1", "D2:1"], "category": 1},
        {"question": "When did Mel start violin?", "answer": 2023, "evidence": ["D1:1; D9:9"],
         "category": 2},
        {"question": "What is the cat called?", "answer": "Pip", "evidence": [], "category": 4},
        {"question": "Does Mel play drums?", "adversarial_answer": "no", "evidence": ["D1:1"],
         "category": 5},
    ]
    other = {"speaker_a": "A", "speaker_b": "B", "session_1_date_time": "1:00 pm on 1 May, 2023",
             "session_1": [turn("D1:1", "A", "Hello.")]}
    samples = [{"sample_id": "conv-syn-1", "conversation": conv, "qa": qa,
                "event_summary": {"x": SENTINEL}, "session_summary": {"x": SENTINEL},
                "observation": {"x": SENTINEL}},
               {"sample_id": "conv-syn-2", "conversation": other,
                "qa": [{"question": "Q?", "answer": "A", "evidence": ["D1:1"], "category": 4}]}]
    sha = _write(root / "data/locomo/v1", {"locomo10.json": json.dumps(samples)})
    return _config("locomo", "v1", sha, {
        "dev": {"kind": "development", "histories": ["conv-syn-1"],
                "counts": {"histories": 1, "messages": 3, "read_tasks": 3, "gold": 3}},
        "held-out": {"kind": "held-out", "histories": ["conv-syn-2"]}})


def longmemeval(root: Path) -> BenchmarkConfig:
    def item(qid, answer_session):
        return {
            "question_id": qid, "question_type": "knowledge-update",
            "question": "Where does the user work now?", "answer": f"Leeds {SENTINEL}",
            "question_date": "2023/06/01 (Thu) 10:00",
            "haystack_session_ids": ["sess_a", "sess_b", "sess_a"],
            "haystack_dates": ["2023/05/20 (Sat) 02:21", "2023/05/25 (Thu) 09:00",
                               "2023/05/27 (Sat) 11:30"],
            "haystack_sessions": [
                [{"role": "user", "content": "I work in York."},
                 {"role": "assistant", "content": "Noted."}],
                [{"role": "user", "content": "I moved to Leeds.", "has_answer": True},
                 {"role": "assistant", "content": " ", "has_answer": False}],
                [{"role": "user", "content": "I work in York."},
                 {"role": "assistant", "content": "Noted."}],
            ],
            "answer_session_ids": [answer_session],
        }

    items = [item("q1", "sess_b"), item("q2_abs", "sess_b")]
    sha = _write(root / "data/longmemeval-s/v1", {"longmemeval_s_cleaned.json": json.dumps(items)})
    return _config("longmemeval-s", "v1", sha, {
        "dev": {"kind": "development", "histories": ["q1"],
                "counts": {"histories": 1, "messages": 5, "read_tasks": 1, "gold": 1}},
        "held-out": {"kind": "held-out", "histories": ["q2_abs"]}})


def halumem(root: Path) -> BenchmarkConfig:
    def session(start, turns, questions):
        dialogue = [{"role": role, "content": text, "timestamp": start, "dialogue_turn": i // 2}
                    for i, (role, text) in enumerate(turns)]
        session = {"start_time": start, "end_time": start, "dialogue": dialogue,
                   "dialogue_turn_num": len(turns) // 2, "dialogue_token_length": 10,
                   "memory_points_count": 1,
                   "memory_points": [{"index": 0, "memory_content": f"works as nurse {SENTINEL}",
                                      "memory_type": "Persona Memory", "is_update": "False",
                                      "original_memories": [], "timestamp": start,
                                      "event_source": 0, "importance": 0.5,
                                      "memory_source": "secondary"}]}
        if questions:
            session["questions"] = questions
            session["question_count"] = len(questions)
        return session

    question = {"question": "What is the user's job?", "answer": f"nurse {SENTINEL}",
                "evidence": [{"memory_content": "works as nurse", "memory_type": "Persona Memory"}],
                "difficulty": "easy", "question_type": "Basic Fact Recall"}
    user = {"uuid": "user-1", "persona_info": SENTINEL, "total_dialogue_token_length": 20,
            "total_question_count": 1, "token_cost": {"current_stage": {}, "cumulative": {}},
            "sessions": [session("Sep 19, 2025, 08:32:00",
                                 [("user", "I am a nurse."), ("assistant", "Great.")], [question]),
                         session("Sep 20, 2025, 09:00:00",
                                 [("user", "Busy day."), ("assistant", "Rest well.")], [])]}
    other = dict(user, uuid="user-2")
    sha = _write(root / "data/halumem-medium/v1", {
        "HaluMem-Medium.jsonl": json.dumps(user) + "\n" + json.dumps(other) + "\n"})
    return _config("halumem-medium", "v1", sha, {
        "dev": {"kind": "development", "histories": ["user-1"],
                "counts": {"histories": 1, "messages": 4, "read_tasks": 1, "gold": 1}},
        "held-out": {"kind": "held-out", "histories": ["user-2"]}})


def memoryagentbench(root: Path) -> BenchmarkConfig:
    import pyarrow as pa
    import pyarrow.parquet as pq

    def meta(source, qa_ids, **extra):
        base = {"demo": None, "haystack_sessions": None, "keypoints": None,
                "previous_events": None, "qa_pair_ids": qa_ids, "question_dates": None,
                "question_ids": None, "question_types": None, "source": source}
        base.update(extra)
        return base

    lme_context = repr(["Chat Time: 2023/05/20 (Sat) 02:21",
                        [{"role": "user", "content": "I adopted a cat."}],
                        "Chat Time: 2023/05/21 (Sun) 08:00",
                        [{"role": "user", "content": "The cat is called Pip."},
                         {"role": "assistant", "content": "Lovely name."}]])
    ar = [{"context": lme_context, "questions": ["What is the cat called?", "When?"],
           "answers": [[f"Pip {SENTINEL}"], ["May"]],
           "metadata": meta("longmemeval_s*", ["longmemeval_s*_no0", "longmemeval_s*_no1"],
                            question_dates=["2023/06/01 (Thu) 10:00"] * 2,
                            question_ids=["aa11", "bb22_abs"],
                            question_types=["single-session-user", "temporal-reasoning"])},
          {"context": "other", "questions": ["x"], "answers": [["y"]],
           "metadata": meta("eventqa_full", ["e0"])}]
    facts = "Here is a list of facts:\n" + "\n".join(f"{i}. Fact number {i}." for i in range(5))
    cr = [{"context": facts + "\n", "questions": ["Q0?", "Q1?"], "answers": [["A0"], ["A1"]],
           "metadata": meta("factconsolidation_sh_6k", ["fc_sh_6k_no0", "fc_sh_6k_no1"])}]
    files = {}
    for name, rows in (("Accurate_Retrieval-00000-of-00001.parquet", ar),
                       ("Conflict_Resolution-00000-of-00001.parquet", cr)):
        sink = pa.BufferOutputStream()
        pq.write_table(pa.Table.from_pylist(rows), sink)
        files[name] = sink.getvalue().to_pybytes()
    sha = _write(root / "data/memoryagentbench/v1", files)
    dev = ["longmemeval_s*:0:longmemeval_s*_no0", "factconsolidation_sh_6k:0:fc_sh_6k_no0"]
    held = ["longmemeval_s*:0:longmemeval_s*_no1", "factconsolidation_sh_6k:0:fc_sh_6k_no1"]
    return _config("memoryagentbench", "v1", sha, {
        "dev": {"kind": "development", "tasks": dev,
                "counts": {"histories": 2, "messages": 5, "read_tasks": 2, "gold": 2}},
        "held-out": {"kind": "held-out", "tasks": held}}, adapter={"facts_per_chunk": 2})


def multiwoz(root: Path) -> BenchmarkConfig:
    def legacy(train_dest, extra_dom=None):
        meta = {"train": {"book": {"booked": [], "people": ""},
                          "semi": {"destination": train_dest, "day": "not mentioned",
                                   "arriveBy": "", "leaveAt": "", "departure": ""}},
                "hospital": {"book": {"booked": []}, "semi": {"department": extra_dom or ""}}}
        return meta

    texts = ["I need a train to Cambridge.", "There is one at 9:00.", "Book it for 2.",
             "Done."]
    log24 = [{"text": texts[0], "metadata": {}},
             {"text": texts[1], "metadata": legacy("cambridge")},
             {"text": texts[2], "metadata": {}},
             {"text": texts[3], "metadata": legacy("cambridge", "cardiology")}]
    log21 = [dict(t, dialog_act={"Train-Inform": [["Dest", "cambridge"]]}, span_info=[])
             for t in log24]
    turns22 = [{"turn_id": str(i), "speaker": "USER" if i % 2 == 0 else "SYSTEM",
                "utterance": t, "frames": [{"service": "train", "slots": [], "actions": [],
                                            "state": {"active_intent": "find_train",
                                                      "requested_slots": [],
                                                      "slot_values": {"train-destination":
                                                                      ["cambridge"]}}}]
                if i % 2 == 0 else []} for i, t in enumerate(texts)]
    goal = {"train": {"info": {"destination": SENTINEL}}}
    dialogues = {"SYN0001.json": {"goal": goal, "log": log24},
                 "SYN0002.json": {"goal": goal, "log": log24}}
    dialogues21 = {k: {"goal": goal, "log": log21} for k in dialogues}
    sha24 = _write(root / "data/multiwoz/2.4", {
        "MULTIWOZ2.4/data.json": json.dumps(dialogues),
        "MULTIWOZ2.4/valListFile.json": "SYN0001.json\n",
        "MULTIWOZ2.4/testListFile.json": "SYN0002.json\n",
        "MULTIWOZ2.4/dialogue_acts.json": json.dumps(
            {"SYN0001": {"1": {"Train-Inform": [["Leave", "9:00"]]}}})})
    sha21 = _write(root / "data/multiwoz/2.1", {"MultiWOZ_2.1/data.json": json.dumps(dialogues21)})
    sha22 = _write(root / "data/multiwoz/2.2", {
        "dev/dialogues_001.json": json.dumps([{"dialogue_id": "SYN0001.json",
                                               "services": ["train"], "turns": turns22}]),
        "test/dialogues_001.json": json.dumps([{"dialogue_id": "SYN0002.json",
                                                "services": ["train"], "turns": turns22}]),
        "dialog_acts.json": json.dumps({"SYN0001.json": {"1": {"dialog_act": {"Train-Offer": []},
                                                              "span_info": []}}})})
    return _config("multiwoz", "2.4", sha24, {
        "dev": {"kind": "development", "history_list_file": "MULTIWOZ2.4/valListFile.json",
                "counts": {"histories": 1, "messages": 4, "read_tasks": 2, "gold": 6}},
        "held-out": {"kind": "held-out", "history_list_file": "MULTIWOZ2.4/testListFile.json"}},
        adapter={"split_dirs_22": {"dev": "dev", "held-out": "test"}},
        extra={"2.2": sha22, "2.1": sha21})


BUILDERS = {"locomo": locomo, "longmemeval-s": longmemeval, "halumem-medium": halumem,
            "memoryagentbench": memoryagentbench, "multiwoz": multiwoz}


def build(slug: str, root: Path) -> BenchmarkConfig:
    return BUILDERS[slug](root)
