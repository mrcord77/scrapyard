# Part Metadata Schema (`scrapyard/catalog@1`)

Every part carries a JSON metadata block in its module docstring, fenced by:

```
### PART-META-JSON
{ ...json... }
### END-PART-META
```

`tools/index_catalog.py` parses these to build `catalog.json`. Keep it valid
JSON and current with the code.

## Fields

| Field | Type | Meaning |
|---|---|---|
| `name` | string | Part name = filename without `.py`. |
| `layer` | string | Owning capability layer (the directory). |
| `purpose` | string | One sentence: what capability this provides. |
| `addition` | bool | `true` if added beyond the original capability map. |
| `status` | `"core"` \| `"skeleton"` | `core` = implemented; `skeleton` = interface only. |
| `dependencies` | string[] | pip names to install (e.g. `"passlib[argon2]"`). Empty = stdlib only. |
| `inputs` | string | What the public functions/classes take. |
| `outputs` | string | What they return / produce. |
| `files_created` | string[] | Files this part writes at runtime (configs, uploads). `[]` if none. |
| `security_notes` | string | **Mandatory, honest.** Risks + the safe way to use it. |
| `ai_usage` | string | How an AI assistant should pick up and wire this part. |
| `example` | string | A copy-pasteable import/usage line. |
| `import_path` | string | Dotted path, e.g. `scrapyard.identity.password_hashing`. |

## Status contract

- **core** — body is real; importing and calling it works once `dependencies`
  are installed.
- **skeleton** — body contains an explicit implementation placeholder. The
  metadata still defines the intended contract without pretending the behavior
  is complete.

## Adding or upgrading a part

1. `python tools/new_part.py <layer> <name> "purpose" [deps…]` (or hand-add to
   the taxonomy in `tools/scaffold_parts.py` for permanence).
2. Implement the body; set module `STATUS = "core"` and `"status": "core"`.
3. `python tools/index_catalog.py` to refresh `catalog.json`.
