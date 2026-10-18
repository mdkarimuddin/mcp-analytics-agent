# Limitations

- **Synthetic, small data.** 12 tables and about 12k rows in SQLite. It says nothing about warehouses with hundreds
  of tables, slow queries or concurrent users.
- **Blocked columns are a hard-coded list.** Real deployments need classification from a data catalogue or policy
  engine, not a constant in `db.py`.
- **Statement semantics.** SQLite functions allowed by the allow-list can still be expensive; the 3 s limit is the
  backstop. The progress-handler limit is approximate.
- **Restore is coarse.** Restoring a snapshot also discards any later approved changes.
- **Prompt injection is mitigated, not solved.** The agent cannot write, drop or read blocked columns, but it can
  still be misled into a wrong answer or a poor proposal. Human review of proposals is the final control.
- **Single user, no authentication.** Local files and a CLI. No role-based access.
- **Evaluation scope.** 45/45 runs passed (15 cases x 3 trials), but the cases are written by the author and mostly
  single-query questions. Passing shows the guardrails and schema exploration on anticipated cases, not general
  robustness. See `docs/EVAL_RESULTS.md`.
- **No deployment pipeline.** CI runs lint, tests and a Docker build. There is no hosted instance.
