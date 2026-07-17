# v0.5.2 evidence recovery and private cache seeding

## What changed

CIB now distinguishes three facts that v0.5.1 could conflate:

1. a completed agent opportunity has a unique terminal session;
2. a provider can fail before any session exists;
3. a per-trial deadline can end without Promptfoo retaining public assignment
   identity in the result row.

This is an evidence-integrity repair. It does not turn an invalid prior study
into a confirmatory result.

## Failure classes and estimands

`pre_session_transport` means the pinned provider returned the exact cloud-config
bootstrap error before any session, target action, marker, or nonce recovery was
observed. `per_trial_timeout` remains reserved for the declared evaluation
deadline. Whole-study timeouts still make a study invalid.

A harness failure scores zero in CIB's end-to-end assigned-attempt outcome. A
scientific protocol that claims agent-routing behavior must instead treat
pre-session transport failures and evidence-less timeouts as missing behavioral
outcomes and preregister its missing-data sensitivity analysis.

## Frozen-ledger recovery

Promptfoo may redact a timed-out row's trial id. CIB recovers that assignment only
when all of these checks pass:

- `tests.jsonl` has the same SHA-256 digest before and after execution;
- every result has one exact integer `testIdx`;
- indices are unique and cover the complete frozen ledger;
- ordinary rows validate the same index-to-assignment mapping;
- the recovered row is an actual per-trial timeout.

Recovered evidence is labeled `frozen_tests_ledger`. It is not written into or
counted as an original protected provider archive.

## Private cloud-config seed

Large concurrent cold starts can contend while fetching the same signed Codex
cloud-config bundle. `--cloud-config-seed` snapshots a private signed-format cache
file once, validates its structure and freshness, and writes the exact bytes into
every 0700 trial `CODEX_HOME` as a distinct 0600 file.

CIB does not cryptographically validate the provider signature; Codex remains
responsible for accepting it. CIB records only the digest, version, timestamps,
required validity window, and post-run copy counts. The signed payload contains
account identifiers and policy data and must never be published.

Use `--cloud-config-min-validity-seconds` to make a frozen protocol fail before
model calls when its explicit seed cannot cover the declared family window.

## Frozen v2 recovery check

After the repair implementation was complete, the normalizer was applied
offline to the prior 1,152-row v2 archive. This diagnostic made no model calls and
does not rehabilitate v2 as confirmatory evidence. It recovered all eight family
audits with:

- 1,152 unique rows;
- 680 behavioral successes under the original exact scorer;
- 35 harness failures, comprising 26 pre-session transport failures and nine
  per-trial timeouts;
- nine assignments recovered from the sealed ledger;
- zero scorer disagreements and zero index/assignment disagreements.

These counts are regression evidence for the repaired evidence contract only.
Any v2 effect estimate remains post-outcome recovery/sensitivity evidence.
