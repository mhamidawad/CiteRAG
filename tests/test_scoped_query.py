import unittest
from citerag.semantic import lexical_content_query,support_terms

class ScopedQueryTests(unittest.TestCase):
    aliases={'opencode-eva':{'opencode-eva'}}
    def test_scoped_history_query_focuses_on_content(self):
        value=lexical_content_query('Archived RAG conversation project opencode-eva',{'opencode-eva'},self.aliases)
        self.assertEqual(support_terms(value),{'rag'})
    def test_exact_filename_is_not_stripped_as_navigation(self):
        value=lexical_content_query('Find opencode.json in project opencode-eva',{'opencode-eva'},self.aliases)
        self.assertIn('opencode.json',value)
    def test_unscoped_query_is_preserved(self):
        self.assertEqual(lexical_content_query('Where is generation routed?',set(),self.aliases),'Where is generation routed?')
    def test_metadata_only_query_keeps_a_searchable_fallback(self):
        value=lexical_content_query('Archived conversation project opencode-eva',{'opencode-eva'},self.aliases)
        self.assertTrue(value.strip())
