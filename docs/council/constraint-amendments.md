# Constraint-test amendments for the council layer

`tests/test_constraints.py` currently enforces the substrate's discipline
so well that it enforces the *absence of the product*: no interaction
mechanics, no writers beyond the ledger, no external write verbs
anywhere. Those bans were right for the substrate build and must be
lifted **deliberately, one seam at a time** — not eroded. This document
is the spec for that change; the tests themselves do not change until
council code lands.

## What changes

1. **Write-verb allowlist gains exactly one module.**
   `_WRITE_VERB_ALLOWLIST = {"replay.py"}` becomes
   `{"replay.py", "executors/seerr.py"}` (path-qualified, not basename,
   when implemented). The guard test
   (`test_write_verb_allowlist_is_tight`) is updated to pin exactly this
   two-element set — it exists precisely so this list cannot grow
   silently. Nothing else is exempted: not the council services, not the
   Discord gateway, not the TMDB client.

2. **New executor-isolation tests** (additions, not relaxations):
   - only `executors/` may import the Seerr write client;
   - the executor module is constructed only behind the phase-A flag;
   - an `executions` audit row precedes any outbound call (write-ahead
     audit, asserted via a fake transport);
   - `COSTANZA_READ_ONLY=true` forces dry-run through every path;
   - phase B flag defaults OFF in code and in the shipped example policy.

3. **The votes/interaction ban is lifted for the council tables only.**
   There is no literal "no votes writer" test today — the ban lives in
   the scope prose and in the absence of writers. When council migrations
   land, `signals` keeps its constraint-by-convention (append-only raw
   capture; the only writers are the capture paths), asserted by a new
   test that greps for `INSERT INTO signals` writers outside the capture
   modules. Votes/interest/pleas writers live in the council service
   layer and need no exemption because they are internal store writes,
   which were never banned.

4. **Discord import confinement is unchanged.** The interaction gateway
   grows inside `adapters/discord/`; `test_no_discord_import_outside_adapter`
   keeps passing untouched. Gateway logic that is domain-shaped (tally
   rules, thresholds) belongs in the council layer — the import test is
   what keeps that boundary honest.

5. **LLM bans stay until the LLM phase.** `test_no_llm_or_prompt_code`
   and the forbidden-dependency list are untouched by council v1 (the
   council loop must work with the LLM off). When plea summarization
   lands (v2), the amendment is: allow the gateway-client module only
   (litellm is reached over HTTP via httpx — the *dependency* ban on
   litellm/openai/anthropic SDKs never needs lifting), and add tests that
   member-authored text cannot reach an external route while no local
   route is configured (OQ-13).

6. **Chaski/deps/read-only-clients tests are untouched.** The TMDB client
   joins `clients/` under the same GET-only scan that covers the tree.

## What explicitly does not change

- 202-always ingest, ledger exactly-once, kill-switch semantics, identity
  map discipline — no council feature is allowed to weaken a substrate
  test to pass.
- ADR-0003: no code path that deletes media, in any phase — the write
  allowlist above is for Seerr create-request (and later downgrade via
  the same executor discipline) only.
- The bearer-token API stays read-only (plus the existing kill switch):
  votes arrive attributed through Discord identity or not at all in v1 —
  an unattributed API vote endpoint would bypass the entire authz model.

## Sequencing

Amendment lands in the same commit as the code it licenses (allowlist
entry + executor module + isolation tests together), so at no commit does
the tree contain an unused exemption or an unlicensed write path.
