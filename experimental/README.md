# experimental/

**Status: not supported. Not part of v0.2.0. Do not import.**

This directory holds code preserved from pre-v0.2.0 phases of the project —
the flat-layout prototypes, early orchestration spikes, and adapter sketches
that informed the current design under `src/stc_framework/`.

## Why it exists

When the repo was restructured to the packaged `src/` layout for v0.2.0, the
earlier code wasn't deleted — it was moved here so git history stays
continuous and we retain a record of the design exploration.

## What you should know before touching anything here

- **No tests cover this code.** The test suite under `tests/` exercises
  `src/stc_framework/` only.
- **No CI runs it.** Lint, type, and coverage gates exclude this tree.
- **No compliance posture.** The AIUC-1 / SEC 17a-4 claims in the root
  `README.md` describe the v0.2.0 package, not the code in here.
- **Imports may be broken.** Cross-references to `spec/`, `reference_impl/`,
  etc. may not resolve — several files were written against a flat layout
  that no longer exists.
- **It will not be maintained.** Dependency upgrades, security patches,
  and bug fixes target `src/stc_framework/` only.

## When is it appropriate to use something from here?

- **Reference while reviewing a design decision** — git blame and the
  original diff context are intact.
- **Lift and port a specific idea** into the supported package, with its
  own tests, type annotations, and documentation.

Copy-pasting a file out of here into production code is not supported.

## Will this directory be removed?

Possibly, once enough time has passed that the history is no longer
load-bearing for onboarding or design review. Until then, treat it as an
append-only archive.
