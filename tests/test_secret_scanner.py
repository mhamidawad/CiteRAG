import importlib.util
from pathlib import Path
import unittest

class SecretScannerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        p=Path(__file__).resolve().parents[1]/"tasks/scan-secrets.py"
        spec=importlib.util.spec_from_file_location("citerag_scanner",p)
        cls.mod=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.mod)
    def test_detects_constructed_token_types_without_echoing_values(self):
        samples=[
            "sk-"+"A"*24,
            "ghp_"+"A"*30,
            "ses_"+"A"*24,
            "https"+"://user:password@example.invalid/path",
            "BEGIN"+" PRIVATE KEY",
            "Authorization: Bearer "+"B"*30,
        ]
        for sample in samples:
            with self.subTest(index=samples.index(sample)):
                self.assertTrue(self.mod.issues_for_line("docs/sample.md",sample))
    def test_allows_only_expected_provenance(self):
        brand="moe"+"-opencode-rag"
        self.assertFalse(self.mod.issues_for_line("NOTICE","Derived from "+brand))
        self.assertTrue(self.mod.issues_for_line("docs/sample.md","Derived from "+brand))
    def test_exact_runner_allowlist_does_not_hide_other_references(self):
        runner="    runs-on: "+"ub"+"untu-24.04"
        self.assertFalse(self.mod.issues_for_line(".github/workflows/tests.yml",runner))
        self.assertTrue(self.mod.issues_for_line("docs/sample.md",runner))
        self.assertTrue(self.mod.issues_for_line(".github/workflows/tests.yml",runner+" # unexpected"))

    def test_old_circleci_documentation_exact_line_exception(self):
        line="The existing Supervisor still runs on `"+"moe"+"-instance`. This preflight"
        self.assertFalse(self.mod.issues_for_line("docs/circleci-thirty-slots.md",line))
        self.assertTrue(self.mod.issues_for_line("docs/sample.md",line))

    def test_history_audit_all_reachable_commits(self):
        self.assertEqual(self.mod.scan_history(),0)

    def test_safe_defaults(self):
        self.assertFalse(self.mod.issues_for_line(".env.example","CITERAG_OMNIROUTE_API_KEY="))
        self.assertFalse(self.mod.issues_for_line("citerag/answer.py",'api_key=os.getenv("CITERAG_OMNIROUTE_API_KEY","")'))

    def test_documentation_refresh_runner_exception_is_exact_and_path_scoped(self):
        for label in ("ub"+"untu-latest", "ub"+"untu-24.04"):
            line="    runs-on: "+label
            self.assertFalse(self.mod.issues_for_line(".github/workflows/context7-refresh.yml",line))
            self.assertTrue(self.mod.issues_for_line("docs/sample.md",line))
            self.assertTrue(self.mod.issues_for_line(".github/workflows/context7-refresh.yml",line+" # changed"))
        token="Bearer "+"A"*24
        self.assertTrue(self.mod.issues_for_line(".github/workflows/context7-refresh.yml",token))
