"""llm/prompts.py and llm/structured.py."""

import hashlib
import tempfile
import unittest
from pathlib import Path

from grace.llm.prompts import PromptError, load_prompt, tree_sha256
from grace.llm.structured import load_schema, parse

FIXTURE_RESOURCES = Path(__file__).resolve().parents[1] / "fixtures" / "resources"


def make_prompt(root: Path, name: str, system: str, user: str) -> None:
    (root / name).mkdir(parents=True)
    (root / name / "system.txt").write_text(system, encoding="utf-8")
    (root / name / "user.txt").write_text(user, encoding="utf-8")


class PromptsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_render_puts_the_fixed_prefix_first(self):
        make_prompt(self.root, "p", "Fixed rules.\n", "Context:\n{{context}}\n\nQ: {{question}}\n")
        prompt = load_prompt("p", root=self.root)
        self.assertEqual(prompt.variables, ("context", "question"))
        messages = prompt.render(context="[D1:1] a {{question}}", question="why?")
        self.assertEqual(messages[0], {"role": "system", "content": "Fixed rules.\n"})
        # values are inserted literally, never re-expanded
        self.assertEqual(messages[1]["content"], "Context:\n[D1:1] a {{question}}\n\nQ: why?\n")

    def test_wrong_variables_and_malformed_templates_fail(self):
        make_prompt(self.root, "p", "", "{{a}} {{b}}")
        prompt = load_prompt("p", root=self.root)
        self.assertEqual(prompt.render(a="1", b="2"), [{"role": "user", "content": "1 2"}])
        for values in ({"a": "1"}, {"a": "1", "b": "2", "c": "3"}, {"a": "1", "b": 2}):
            with self.subTest(values=values), self.assertRaises(PromptError):
                prompt.render(**values)
        make_prompt(self.root, "sys", "rules {{x}}", "{{y}}")
        make_prompt(self.root, "stray", "rules", "{{y}} {{ bad-name }}")
        make_prompt(self.root, "none", "rules", "no placeholder")
        for name in ("sys", "stray", "none", "missing"):
            with self.subTest(name=name), self.assertRaises(PromptError):
                load_prompt(name, root=self.root)

    def test_checksum_is_pinned(self):
        make_prompt(self.root, "p", "rules", "{{x}}")
        digest = load_prompt("p", root=self.root).sha256
        self.assertEqual(load_prompt("p", expected_sha256=digest, root=self.root).sha256, digest)
        (self.root / "p" / "system.txt").write_text("rules changed", encoding="utf-8")
        with self.assertRaises(PromptError):
            load_prompt("p", expected_sha256=digest, root=self.root)

    def test_tree_sha256_is_sha256sum_style(self):
        lines = []
        for path in sorted(p for p in FIXTURE_RESOURCES.rglob("*") if p.is_file()):
            rel = path.relative_to(FIXTURE_RESOURCES).as_posix()
            lines.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {rel}\n")
        expected = hashlib.sha256("".join(lines).encode()).hexdigest()
        self.assertEqual(tree_sha256(FIXTURE_RESOURCES), expected)
        self.assertEqual(tree_sha256(self.root / "absent"), hashlib.sha256(b"").hexdigest())


class StructuredTest(unittest.TestCase):
    def setUp(self):
        self.answer = load_schema("answer")

    def test_the_four_permitted_outputs(self):
        good = [
            '{"output": "answer", "answer": "15 minutes", "cited_ids": ["sess_b:0"]}',
            '```json\n{"output": "answer", "answer": ["a", "b"], "cited_ids": ["D1:1"]}\n```',
            '<think>\n\n</think>\n\n{"output": "state", "state": {"train-day": "monday"}, '
            '"cited_ids": []}',
            '{"output": "retrieve", "query": "commute"}',
            '{"output": "unknown", "cited_ids": []}',
        ]
        for text in good:
            with self.subTest(text=text):
                self.assertTrue(parse(text, self.answer).ok, parse(text, self.answer).error)

    def test_failures_are_returned_not_repaired(self):
        bad = [
            "", None, "15 minutes",
            '{"output": "answer", "answer": "x"}',  # no citations
            '{"output": "answer", "answer": "x", "cited_ids": []}',
            '{"output": "unknown", "cited_ids": ["D1:1"]}',
            '{"output": "follow-up", "question": "which one?"}',
            '{"output": "answer", "answer": "x", "cited_ids": ["D1"]} trailing',
            '{"output": "retrieve", "query": "x", "extra": 1}',
        ]
        for text in bad:
            with self.subTest(text=text):
                result = parse(text, self.answer)
                self.assertFalse(result.ok)
                self.assertIsNone(result.value)
                self.assertTrue(result.error)


if __name__ == "__main__":
    unittest.main()
