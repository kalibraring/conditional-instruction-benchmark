# Open-source project checklist

This checklist turns the repository into a project people can understand, use,
trust, and contribute to.

## Foundation

- [x] One-sentence value proposition and alpha status in the README.
- [x] Copy-pasteable setup, zero-call plan, smoke run, and success artifact.
- [x] Detectable MIT license in the repository and package metadata.
- [x] Contribution guide, code of conduct, security policy, support route, and
  governance model.
- [x] Changelog, semantic version, roadmap, citation metadata, and release notes.
- [x] Public issue forms and pull-request template.

## Reproducibility and quality

- [x] Pinned Python and Node dependency locks.
- [x] CI runs the same tests, build, dependency, and publication checks used
  locally.
- [x] GitHub Actions are pinned to immutable commit SHAs.
- [x] Wheel and source distribution build from a clean tree.
- [x] Backend capability declarations and synthetic adapter tests.
- [x] Sanitized aggregate migration evidence without raw private trials.

## Security and privacy

- [x] Generated results, private manifests, auth links, caches, and build trees
  are ignored and excluded from packages.
- [x] Deterministic publication checker rejects forbidden paths, symlinks,
  oversized files, absolute workstation paths, and common credential forms.
- [x] Local secret scanner runs before the first commit.
- [x] GitHub secret scanning and private vulnerability reporting enabled.
- [x] Dependabot configuration for Python, npm, and GitHub Actions.
- [x] CI uses read-only permissions except the tag-only release job.

## Community and maintenance

- [x] Maintainer and decision boundaries documented.
- [x] User support, bugs, features, research changes, and security reports route
  to different channels.
- [x] Compatibility-sensitive changes require a design issue and evidence.
- [ ] Add a second maintainer after sustained contribution.
- [ ] Publish a stable deprecation policy before 1.0.
- [ ] Add OpenSSF Scorecard monitoring after the repository has public history.

GitHub's [community profile](https://docs.github.com/en/communities/setting-up-your-project-for-healthy-contributions/about-community-profiles-for-public-repositories)
defines the baseline health files. The [OpenSSF Scorecard](https://openssf.org/scorecard/)
adds continuous security-health signals. Python distributions follow the
[PyPA build and publish guidance](https://packaging.python.org/en/latest/guides/section-build-and-publish/).
