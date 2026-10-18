# Design decisions

**Free-form SQL, but inside a sandbox.** The first project (`mcp-job-agent`) avoided SQL tools entirely. This one
targets unfamiliar databases, where questions are open-ended, so a read-only SQL tool is the right tool. Safety moves
from "no SQL" to enforcement inside SQLite itself.

**The authorizer is the main control, not a regex.** Pattern matching on SQL text is easy to bypass (aliases, CTEs,
`SELECT *`). SQLite's authorizer callback sees every column read and every function call after parsing, so blocking
`cust.email` works however the query is written.

**Defence in depth.** One statement only, SELECT/WITH prefix check, `mode=ro` connection, authorizer, function
allow-list, row cap and time limit. Any single layer failing should not be enough to do harm.

**Propose, dry-run, approve, snapshot.** A proposal is executed inside a transaction that is always rolled back, to
count affected rows. Approval takes a snapshot with SQLite's backup API, re-applies the statement in a transaction,
verifies the row count equals the preview, then commits. Restore copies the snapshot back.

**Snapshot restore instead of per-row undo.** Generic undo for arbitrary UPDATE/DELETE statements is hard to get
right. A full snapshot is simple and verifiable. The trade-off is that it also discards later changes (documented).

**Metadata in a separate database.** Proposals and the audit log live in `meta.db`, so the analytical database can
be opened strictly read-only.

**Human-only actions stay out of MCP.** Approve, reject and restore are CLI commands. A test asserts the registered
MCP tool list equals the allow-list.

**Execution-based evaluation.** Expected values are computed by SQL on the same data, so answers are checked
against ground truth rather than keywords.

**Python 3.10 compatibility.** `set_authorizer(None)` misbehaves before Python 3.11, so a permissive authorizer
function is used to "clear" it.
