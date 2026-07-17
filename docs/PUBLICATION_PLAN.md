# Publication plan

## Goal

Publish a small, reproducible scientific product under
`kalibraring/conditional-instruction-benchmark` without exposing the private
research archive or coupling users to one machine.

## Release gate

The release is allowed only when all checks pass:

1. source contains no raw results, private manifests, auth links, dependency
   trees, caches, or build environments;
2. publication and independent secret scans report no findings;
3. all deterministic tests pass from a clean environment;
4. wheel and source distribution contain only intended files;
5. `cib doctor` and zero-call `cib plan` work from the release checkout;
6. package, CLI, changelog, citation, and tag versions agree;
7. GitHub CI passes on the public commit;
8. the tag-triggered release contains built artifacts and checksums.

## Execution

### Phase 1 — public tree

- Copy only reusable source, tests, adapters, and methodology.
- Add product, community, security, governance, and release files.
- Replace machine paths with repository-relative commands.
- Publish only aggregate migration evidence.

### Phase 2 — local proof

- Install from lockfiles.
- Run tests, build, package inspection, publication check, and secret scan.
- Initialize Git only after the tree passes, so leaked data never enters public
  history.
- Reinstall the built wheel in an empty environment and run CLI smoke commands.

### Phase 3 — GitHub publication

- Create the public repository with issues, discussions, vulnerability
  reporting, secret scanning, and dependency alerts.
- Push one reviewed `main` commit.
- Wait for CI and inspect failures before tagging.
- Create annotated tag `v0.2.0`; let the tag workflow create the GitHub release.
- Verify repository metadata, topics, community profile, release assets, and
  fresh-clone behavior.

### Phase 4 — product follow-through

- Test onboarding with someone who did not build the project.
- Create PyPI Trusted Publisher configuration with manual environment approval.
- Add a synthetic provider-free demo and separate recovery command.
- Gather reproducibility reports before adding another agent adapter.

## Rollback

Before tagging, fix forward on `main`. After tagging, never replace release
artifacts silently: publish a patch release and explain the defect. If a secret
appears, revoke it first, remove public access if necessary, rewrite affected
history, and document the incident after containment.
