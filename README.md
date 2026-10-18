# mcp-analytics-agent

![CI](https://github.com/mdkarimuddin/mcp-analytics-agent/actions/workflows/ci.yml/badge.svg)

An MCP server and agent that explores an **unfamiliar** multi-table database and answers business questions
with SQL, without being able to read personal data, run destructive statements, or change anything without
human approval. Changes are dry-run first, applied in a transaction, and can be undone from a snapshot.

The demo database is synthetic: 12 tables with terse names (`ord_hdr`, `ord_line`, `rtn`, `cust`...), 3,000 orders,
about 8,000 order lines, generated from a fixed seed. No real people or companies.

## What it does

```
dbagent demo                                  # build the synthetic database
dbagent ask "Which product category has the highest revenue?"
dbagent ask "Set the list price of product 1 to 9.99"   # creates a proposal, changes nothing
dbagent pending                               # you review the proposal
dbagent approve 1                             # snapshot, transaction, row-count check, commit
dbagent restore 1                             # undo by restoring the snapshot
```

## Architecture

```
user -> CLI -> agent loop (Anthropic API, max 8 steps, token budget)
                 |  MCP client (stdio)
            MCP server: list_tables, describe_table, find_columns, run_query, propose_change
                 |
        retail.db  (read-only connection + SQLite authorizer)      meta.db (proposals, audit log)

human-only (CLI, never exposed through MCP): approve, reject, restore
```

## Guardrails (each has a test)

| Risk | Control | Test |
|---|---|---|
| Destructive or multi-statement SQL | Only one `SELECT`/`WITH`; read-only connection; authorizer denies everything except reads | `test_non_select_and_multi_statement_are_rejected` |
| Personal data leaks | Authorizer blocks `cust.email`, `cust.phone`, `emp.email`, `emp.salary` in every form (SELECT *, CTEs, aliases, WHERE) | `test_personal_data_columns_are_blocked_in_every_form` |
| Dangerous functions | Function allow-list (no `load_extension`, `random`) | `test_unapproved_functions_are_denied` |
| Runaway queries | 3 s wall-clock limit, 100-row cap, truncation flag | `test_runaway_query_is_stopped`, `test_row_cap_and_truncation` |
| Schema probing | `sqlite_master` and PRAGMA not reachable through SQL; schema tools instead | `test_schema_tables_are_not_readable_via_sql` |
| Prompt injection in data | One product description contains an injection string; it is only data, and the system prompt marks tool text untrusted | `test_injected_product_description_is_only_data` |
| Unwanted writes | Agent can only *propose*; dry-run in a rolled-back transaction; writable tables `prod`, `ord_hdr`, `ship`; WHERE required; max 100 rows | `test_unsafe_proposals_are_rejected` |
| Bad approvals | Row count re-checked at approval; abort and roll back if it changed | `test_approve_aborts_if_row_count_drifted` |
| Undo | Snapshot before every approved change; `restore` | `test_restore_returns_database_to_snapshot` |
| Untraceable actions | Every call recorded in `audit_log` with actor | `test_audit_log_records_actors` |

## Tests and evaluation

```bash
pip install -e ".[dev]" && pytest --cov=src      # 55 tests incl. a real MCP stdio round trip
export ANTHROPIC_API_KEY=...                      # your own shell only
python eval/run_eval.py --trials 3                # 15 cases against the real model
```

The evaluation is **execution-based**: expected answers are computed by running SQL on the same data
(counts, a revenue sum, a top city, average delivery days), then compared with the agent's answer.
It also checks safety cases (emails, salary, injection, DROP request, price-change request) and that the
database is unchanged afterwards. Results: see `docs/EVAL_RESULTS.md`.

## Status

- Unit and integration tests run in CI (Python 3.10-3.12) plus a Docker build.
- Model-in-the-loop evaluation: 45/45 runs passed (15 cases x 3 trials), 0 unsafe runs, on 18 Oct 2026.
  See `docs/EVAL_RESULTS.md` for what that does and does not show.
- One author, no other users yet. See `docs/LIMITATIONS.md`.
