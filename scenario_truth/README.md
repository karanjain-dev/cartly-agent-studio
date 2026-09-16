# Evaluation-only scenario truth

These JSON files hold the original scenario-only fields and edge tags, keyed by
record ID. World fields remain in ../data/. Runtime tools must not read this
directory. Only fixture validation and tests may join the two layers.

The migration manifest records hashes proving that the split preserves every
original record value and leaves policy.md unchanged. config.json holds the
original scenario-metadata descriptions moved out of runtime configuration.
