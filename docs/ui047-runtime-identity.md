# UI-047 runtime identity prerequisite

The overlay now computes the canonical shared runtime fingerprint for every invocation and rejects a supplied malformed or non-matching fingerprint before tenant writes. Matching and omitted identities report that computed fingerprint. This closes only the bounded overlay identity prerequisite; candidate artifact transport, runtime rendering integration, and real-run proof remain outside this change and UI-047 acceptance remains incomplete.
