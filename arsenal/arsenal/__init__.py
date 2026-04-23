"""NAIL Arsenal — capability provisioning.

Public API:

    from arsenal import (
        mint, verify, inspect,
        set_session_tokens, requires_token,
        sign_blob, verify_blob,
        TokenError, ExpiredToken, ExhaustedToken, MissingToken,
    )
"""
from .tokens import mint, verify, inspect, Token
from .enforcer import (
    set_session_tokens, requires_token,
    MissingToken, ExhaustedToken, ConditionNotMet,
)
from .signing import sign_blob, verify_blob
from .keys import (
    generate_keypair, load_keypair, default_key_dir, IssuerKey,
)
from .errors import TokenError, ExpiredToken

__all__ = [
    "mint", "verify", "inspect", "Token",
    "set_session_tokens", "requires_token",
    "sign_blob", "verify_blob",
    "generate_keypair", "load_keypair", "default_key_dir", "IssuerKey",
    "TokenError", "ExpiredToken", "ExhaustedToken", "MissingToken",
    "ConditionNotMet",
]

__version__ = "0.1.0"
