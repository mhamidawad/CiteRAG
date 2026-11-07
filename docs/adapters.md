# Adapter interface and compatibility

`GET /api/adapters` currently returns identifiers `retrieval-only`, `omniroute` and `opencode`. The API rejects unknown identifiers and nonempty or invalid `adapter_config` before acquiring locks or refreshing context. Legacy `retrieval_only` and `use_native` request booleans are still accepted when no `adapter` is supplied.

| Adapter | Verified | Caution |
| --- | --- | --- |
| retrieval-only | Yes, isolated REST sample | No LLM; cited extractive response |
| omniroute | Registration + legacy unit tests only | Optional model/key/base URL required; real inference untested |
| opencode | Registration + legacy unit tests only | Original native verifier is not part of sanitized standalone package |
| additional agents | Not implemented | Add tests before claiming support |

A future pluggable registry should enforce a `name`, `validate`, `run` contract and a strict JSON schema per adapter. Every generating adapter must pass the same citation and verbatim-claim validation as retrieval-only; a registered name does not imply a verified connection.

## Minimal REST request

```json
{"question":"Which documents are approved?","adapter":"retrieval-only","adapter_config":{}}
```

Do not pass credentials in `adapter_config` or the dashboard. Secrets belong to protected server-side configuration and must never appear in logs or Git.
