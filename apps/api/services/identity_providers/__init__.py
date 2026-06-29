"""Per-provider identity-resolution mixins.

`IdentityResolver` (apps/api/services/identity_resolver.py) composes these
mixins. Provider HTTP/parse logic lives here; orchestration, shared state,
and persistence stay on the resolver class. Behavior is identical to the
former single-file implementation — this is a structural split only.
"""
