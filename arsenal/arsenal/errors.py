"""Arsenal exception hierarchy."""


class TokenError(Exception):
    """Base for all arsenal token errors."""


class ExpiredToken(TokenError):
    """Token's `exp` claim is in the past."""


class InvalidSignature(TokenError):
    """Token signature did not verify against any known issuer key."""


class MalformedToken(TokenError):
    """Token could not be parsed."""


class UnknownIssuer(TokenError):
    """Token's `kid` does not match any loaded issuer key."""
