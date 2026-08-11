# MagAgent 0.70.0 Release Record

MagAgent 0.70.0 focuses on security evidence, provider clarity, and integration reliability.

## Release Scope

- TrustedRouter and Prime Intellect provider support
- dated qualified, compatible, and experimental support claims
- deterministic security assurance and threat-model documentation
- expanded high-risk boundary and durability tests
- Linux, macOS, and Windows public-wheel acceptance workflow
- generalized credentialed provider qualification workflow

## Required Evidence

The release requires lint, typing, documentation drift, deterministic agent evaluations, full
tests, the enforced branch-coverage floor, source/wheel build checks, secret scanning, and the
credential-free security report. GitHub Actions supplies the three-platform wheel acceptance
result. Any approved exception is recorded in generated release evidence rather than hidden by
weakening a test.

The complete local suite passes 777 tests at 67.73% branch-aware coverage. This exceeds the
enforced 64% regression floor but not the roadmap's 72% target. It ships as an explicit medium
exception; focused gateway routing and artifact execution coverage remains follow-up work.

## Support Semantics

`qualified` means the dated live suite covers the advertised behavior. `compatible` means the
adapter, configuration, and catalog checks pass but complete live qualification is pending.
`experimental` identifies a known upstream or implementation limitation. Use
`magent provider matrix` and `magent provider support-report` for the current evidence.

## Known Limits

Provider catalog presence is not a claim of live qualification. Browser, gateway, keyring,
notification, and local-provider behavior still depends on optional platform capabilities.
Approved host commands retain the user's authority unless shell sandboxing is enabled.
