"""Native OpenCode trace evidence gate: exact tool and grounding contract."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from citerag.native_result import evaluate

SPEC = importlib.util.spec_from_file_location(
    "native_bridge_evidence",
    Path(__file__).resolve().parents[1] / "tasks/native_bridge_evidence.py")
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)


class TraceGateTests(unittest.TestCase):
    def test_actual_native_result_fields_pass(self):
        # Synthetic fixture goes through the same validator; no inference.
        from citerag.native_result import ABSTENTION
        event = [
            {"type": "tool_use", "part": {
                "tool": "sample_rag_search",
                "state": {"status": "completed", "output": json.dumps({"results": []})}
            }},
            {"type": "text", "part": {"text": ABSTENTION}},
            {"type": "step_finish", "part": {"reason": "stop"}},
        ]
        out = gate.verify("\n".join(json.dumps(x) for x in event),
                          exit_code=0, tool="sample_rag_search")
        self.assertEqual(out["status"], "PASS")
        self.assertFalse(out["backend_identity_attested"])
        self.assertFalse(out["standalone_production_certified"])
        self.assertEqual(out["native_tool_calls"], 1)

    def test_fails_without_real_tool(self):
        result = gate.verify(json.dumps({"type": "text", "part": {"text": "ok"}}),
                             exit_code=0, tool="sample_rag_search")
        self.assertEqual(result["status"], "FAIL")

    def test_fails_when_nonzero_exit(self):
        from citerag.native_result import ABSTENTION
        data = "\n".join(json.dumps(x) for x in (
            {"type": "tool_use", "part": {"tool": "citerag_search",
                "state": {"status": "completed", "output": '{"results":[]}'}}},
            {"type": "text", "part": {"text": ABSTENTION}},
            {"type": "step_finish", "part": {"reason": "stop"}},
        ))
        self.assertEqual(gate.verify(data, exit_code=1,
                                    tool="citerag_search")["status"], "FAIL")

    def test_rejects_other_tool(self):
        with self.assertRaises(gate.EvidenceError):
            gate.verify("{}", exit_code=0, tool="other_tool")

    def test_source_constraint_not_fabricated(self):
        from citerag.native_result import ABSTENTION
        data = "\n".join(json.dumps(x) for x in (
            {"type": "tool_use", "part": {"tool": "citerag_search",
                "state": {"status": "completed", "output": '{"results":[]}'}}},
            {"type": "text", "part": {"text": ABSTENTION}},
            {"type": "step_finish", "part": {"reason": "stop"}},
        ))
        result = gate.verify(data, exit_code=0, tool="citerag_search",
                             expected_source="docs/architecture.md")
        self.assertEqual(result["status"], "FAIL")
        self.assertFalse(result["source_constraint_matched"])

    def test_file_and_size_guards(self):
        with tempfile.TemporaryDirectory() as dir_:
            path = Path(dir_) / "output.jsonl"
            path.write_text("{}")
            with patch.object(gate, "MAX_TRACE_BYTES", 2):
                self.assertEqual(gate.main([str(path), "--exit-code", "0",
                             "--tool", "citerag_search"]), 2)
            link = Path(dir_) / "link"
            link.symlink_to(path)
            self.assertEqual(gate.main([str(link), "--exit-code", "0",
                            "--tool", "citerag_search"]), 2)

    def test_invalid_source_constraint(self):
        with self.assertRaises(gate.EvidenceError):
            gate.verify("{}", exit_code=0, tool="citerag_search",
                        expected_source="../secrets.txt")


if __name__ == "__main__":
    unittest.main()
