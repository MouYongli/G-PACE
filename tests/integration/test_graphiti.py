"""Graphiti adapter (T034): calls through the model port, constrained decoding, failures, reads.

The pure helpers are tested in every environment. The engine tests need graphiti-core and run only
in the envs/graphiti environment (`envs/graphiti/.venv/bin/python -m unittest
tests.integration.test_graphiti`); elsewhere they are skipped. They use the synthetic LoCoMo
fixture and a deterministic responder that answers each Graphiti call from the JSON schema it was
sent; no score is real.
"""

import json
import re
import socket
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest import mock

from grace.eval.engines.baselines import graphiti as adapter
from grace.eval.engines.baselines.base import EMPTY_CONTEXT
from grace.eval.runner.harness.inputs import load_fixture as load
from grace.eval.runner.harness.models import FakeBackend, RecordingModel
from grace.llm.records import CallLedger

ROOT = Path(__file__).resolve().parents[2]
LOCOMO = ROOT / "tests" / "fixtures" / "benchmarks" / "locomo"
HAS_GRAPHITI = adapter.features()["graphiti-core"] == adapter.GRAPHITI_VERSION


class HelperTest(unittest.TestCase):
    def test_prompt_hash_names_template_and_mode(self):
        names = adapter.prompt_names_by_hash()
        for mode in adapter.STRUCTURED_OUTPUT:
            digest = adapter.prompt_hash("dedupe_edges.resolve_edge", mode)
            self.assertEqual(names[digest], ("dedupe_edges.resolve_edge", mode))
        self.assertNotEqual(adapter.prompt_hash("extract_edges.edge", "json_schema"),
                            adapter.prompt_hash("extract_edges.edge", "json_object"))

    def test_group_id_and_reference_time(self):
        self.assertEqual(adapter.group_id("conv-26"), "conv-26")
        self.assertRegex(adapter.group_id("a/b c"), r"^h[0-9a-f]{16}$")
        self.assertEqual(adapter.reference_time("2023-05-08T13:56"),
                         datetime(2023, 5, 8, 13, 56, tzinfo=UTC))
        self.assertEqual(adapter.reference_time(None), adapter.UNKNOWN_TIME)

    def test_parse_structured(self):
        self.assertEqual(adapter.parse_structured('```json\n{"a": 1}\n```'), {"a": 1})
        for bad in ("", "[1]", "not json"):
            with self.assertRaises(ValueError):
                adapter.parse_structured(bad)

    def test_render_edge(self):
        when = datetime(2023, 5, 7, tzinfo=UTC)
        self.assertEqual(adapter.render_edge("A likes B", ["D1:1"], when, None),
                         "[D1:1] (valid 2023-05-07T00:00 to unknown) A likes B")
        self.assertEqual(adapter.render_edge("A likes B", [], None, None), "A likes B")


def instance(schema, defs):
    """A minimal instance of a JSON schema (required fields only)."""
    if "$ref" in schema:
        return instance(defs[schema["$ref"].rsplit("/", 1)[1]], defs)
    if "anyOf" in schema:
        return None
    kind = schema.get("type")
    if kind == "object":
        return {k: instance(schema["properties"][k], defs) for k in schema.get("required", [])}
    return {"array": [], "string": "x", "integer": 0, "number": 0.0, "boolean": False}.get(kind)


class SchemaResponder:
    """Answers a Graphiti call from the response_format it was sent: entities are the speaker and
    the last word of the message, one fact per message, no duplicates."""

    def __init__(self):
        self.schema = None
        self.entities = []
        self.formats = []

    def __call__(self, messages):
        user = messages[-1]["content"]
        name = self.schema["json_schema"]["name"]
        schema = self.schema["json_schema"]["schema"]
        current = user.split("<CURRENT MESSAGE>", 1)[-1].split("</CURRENT MESSAGE>", 1)[0]
        line = re.search(r"(\w+): (.+)", current)
        if name == "ExtractedEntities" and line:
            last = re.findall(r"[A-Za-z]+", line.group(2))[-1].lower()
            self.entities = [line.group(1), last]
            return json.dumps({"extracted_entities": [
                {"name": e, "entity_type_id": 0} for e in self.entities]})
        if name == "ExtractedEdges" and line and len(self.entities) == 2:
            return json.dumps({"edges": [{
                "source_entity_name": self.entities[0], "target_entity_name": self.entities[1],
                "relation_type": "MENTIONS", "fact": f"{line.group(1)} said: {line.group(2)}",
                "valid_at": None, "invalid_at": None, "episode_indices": [0]}]})
        if name == "NodeResolutions":
            count = re.search(r"ENTITIES contains (\d+) entities", user)
            n = int(count.group(1)) if count else 0
            names = re.findall(r'"name": "([^"]+)"', user.split("<EXISTING ENTITIES>", 1)[0])
            return json.dumps({"entity_resolutions": [
                {"id": i, "name": names[i] if i < len(names) else "x",
                 "duplicate_candidate_id": -1} for i in range(n)]})
        return json.dumps(instance(schema, schema.get("$defs", {})))


class SchemaModel(RecordingModel):
    """The fake port, handing the requested response_format to the responder."""

    def __init__(self, responder, ledger):
        super().__init__(FakeBackend(responder), ledger)
        self.responder = responder

    def chat(self, messages, tag, *, response_format=None, **kwargs):
        self.responder.schema = response_format
        self.responder.formats.append(response_format)
        return super().chat(messages, tag, response_format=response_format, **kwargs)


@unittest.skipUnless(HAS_GRAPHITI, "needs the envs/graphiti environment")
class GraphitiEngineTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.ledger = CallLedger(self.dir / "calls.jsonl", "T034-20261125T000000Z-0000")
        self.item = load(LOCOMO, "streaming").histories[0]

    def engine(self, model, **params):
        engine = adapter.GraphitiEngine(model, max_coroutines=1, **params)
        engine.open(self.item.history)
        return engine

    def read_at(self, version):
        return next(t for t in self.item.reads if t.version == version)

    def test_calls_go_through_the_port_with_json_schema_and_no_socket_is_opened(self):
        responder = SchemaResponder()
        model = SchemaModel(responder, self.ledger)
        with mock.patch.object(socket.socket, "connect", side_effect=AssertionError("network")):
            engine = self.engine(model)
            for message in self.item.messages:
                engine.write(message)
            read = engine.read(self.read_at(5), 256)
        self.assertTrue(all(o["status"] == "ok" for o in engine.outcomes), engine.outcomes)
        names = adapter.prompt_names_by_hash()
        external = [r for r in self.ledger.records if r.call_type == "external"]
        self.assertTrue(external)
        self.assertTrue(all(names[r.prompt_sha256][1] == "json_schema" for r in external))
        self.assertTrue(all(r.category == "W" for r in external))
        self.assertTrue(all(f and f["type"] == "json_schema" for f in responder.formats))
        reads = [r for r in self.ledger.records if r.trigger == "read"]
        self.assertTrue(reads and all(r.call_type == "embed" for r in reads))  # the query only
        self.assertNotEqual(read.context.text, EMPTY_CONTEXT)
        visible = {m.message_id for m in self.item.messages}
        cited = {i for f in read.context.fragments for i in f.evidence_ids}
        self.assertTrue(cited and cited <= visible)
        self.assertLessEqual(read.context.tokens, 256)

    def test_unparsable_output_fails_the_episode_after_graphitis_retries(self):
        model = RecordingModel(FakeBackend(lambda messages: "not json"), self.ledger)
        engine = self.engine(model)
        engine.write(self.item.messages[0])
        self.assertEqual(engine.outcomes[0]["status"], "failed")
        # Graphiti's 4 attempts, each retried once by the port
        external = [r for r in self.ledger.records if r.call_type == "external"]
        self.assertEqual(len(external), adapter.LLM_ATTEMPTS * 2)
        self.assertEqual({r.status for r in external},
                         {"invalid_output"})
        self.assertEqual(engine.episodes, {})  # nothing of the failed episode is kept

    def test_json_object_mode_puts_the_schema_in_the_prompt(self):
        prompts = []

        def responder(messages):
            prompts.append(messages[-1]["content"])
            return "{}"

        model = RecordingModel(FakeBackend(responder), self.ledger)
        engine = self.engine(model, structured_output="json_object")
        engine.write(self.item.messages[0])
        self.assertIn("Respond with a JSON object in the following format", prompts[0])
        names = adapter.prompt_names_by_hash()
        modes = {names[r.prompt_sha256][1] for r in self.ledger.records
                 if r.call_type == "external"}
        self.assertEqual(modes, {"json_object"})


if __name__ == "__main__":
    unittest.main()
