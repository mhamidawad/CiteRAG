"""Read-only native inference resource-gate regression coverage."""
import importlib.util
import unittest
from pathlib import Path

p = Path(__file__).resolve().parents[1] / "tasks/native_inference_preflight.py"
spec = importlib.util.spec_from_file_location("native_inference_preflight", p)
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)

BASE = {"available_memory_mib": 8192, "free_swap_mib": 2048,
        "load_1m": 0.5, "logical_cores": 8, "disk_used_percent": 60.0}


class GateTests(unittest.TestCase):
    def test_healthy_host_ready(self):
        self.assertEqual(gate.assess(BASE), {"ready": True, "blockers": []})

    def test_swap_pressure_denies(self):
        result = gate.assess({**BASE, "free_swap_mib": 386})
        self.assertFalse(result["ready"])
        self.assertIn("SWAP_HEADROOM_LOW", result["blockers"])

    def test_memory_pressure_denies(self):
        result = gate.assess({**BASE, "available_memory_mib": 4096})
        self.assertIn("MEMORY_HEADROOM_LOW", result["blockers"])

    def test_overloaded_cpu_denies(self):
        result = gate.assess({**BASE, "load_1m": 4.5})
        self.assertIn("CPU_LOAD_HIGH", result["blockers"])

    def test_disk_near_limit_denies(self):
        result = gate.assess({**BASE, "disk_used_percent": 85.0})
        self.assertIn("DISK_NEAR_LIMIT", result["blockers"])

    def test_missing_and_invalid_fail_closed(self):
        self.assertFalse(gate.assess({})["ready"])
        self.assertFalse(gate.assess({**BASE, "load_1m": float("nan")})["ready"])
        self.assertFalse(gate.assess({**BASE, "logical_cores": 0})["ready"])


if __name__ == "__main__":
    unittest.main()
