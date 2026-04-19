"""Internal shared helpers used by multiple v0.3.0 subsystems.

Nothing in this package is part of the public API. Import paths under
``stc_framework._internal`` may change between minor versions without
deprecation. Domain modules consume these helpers to avoid reinventing
state machines, alert thresholds, weighted scoring, pattern catalogs,
and TTL arithmetic individually.
"""
