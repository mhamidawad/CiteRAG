# Native OpenCode trace evidence gate

This is an **offline, read-only verification component**, not a model runner,
an MCP authentication mechanism or production certification.

## Usage

Pass an already-recorded sanitized OpenCode JSONL trace, its actual process
exit status, the expected tool and (for backend-specific acceptance) the
expected approved document source:

```sh
python3 tasks/native_bridge_evidence.py /path/to/sanitized-trace.jsonl \
  --exit-code 0 --tool moe-rag_rag_search \
  --expected-source docs/architecture.md
```

The checker invokes CiteRAG's existing native-result validator. It requires
a completed tool event, a legitimate stopped event, verified citation/claim
grounding or a properly supported abstention, zero unexpected tool calls,
and a zero process exit code. It refuses a missing/symlinked/oversized trace,
unapproved tool aliases and unsafe source constraints.

The result contains only status flags and counts, not the model's answer
or underlying document text. Importantly, it always reports
`backend_identity_attested=false` and
`standalone_production_certified=false` because JSONL event evidence
does not cryptographically establish which external MCP server was called.

## Real cross-project verification — November 8, 2026

The **original** RAG project's bounded native run produced an actual
OpenCode JSONL trace with one successful tool event, valid citations and
supported claims. CiteRAG's shared validator accepted the trace.

Requiring `--expected-source docs/architecture.md` **rejected that same
trace** because its actual evidence pointed at the original project's
`docs/rag-integration.md`. This intentional failure is an important
anti-hallucination gate; a successful trace cannot certify a different
retrieval backend merely because its text sounds correct.

No inference was started by this verification. The combined OpenCode
inference → authenticated standalone CiteRAG MCP → source-grounded answer
remains **unverified**.

## Remaining conditions

1. A dedicated, sandboxed OpenCode executor with scoped access to the
   authenticated CiteRAG MCP endpoint, a fresh isolated runtime, token-safe
   initialization, and a hard execution deadline.
2. A trusted mapping of the connected MCP endpoint to its immutable image
   and approved source corpus, beyond a model-generated JSONL trace.
3. A clean real model/tool result on the CiteRAG backend with the exact
   expected source; reject other backends' results.
4. Host resource preflight must return READY (swap currently blocks).
5. CircleCI 20-slot acceptance and production security/rollback gates.

No prod OpenCode, OmniRoute, Compose or cloud runner configuration was
modified by this evidence gate.
