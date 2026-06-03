"""NAIL Shield — prompt-arrival neutralisation.

Public API:

    from shield import process, ShieldedInput

    shielded = process(text, source="email:abc@x.com")
    shielded.text            # canonicalised + provenance-wrapped + scrubbed
    shielded.secrets         # {token: original}  (reversible rehydration)
    shielded.chain_id        # sha256 hex, anchored into AVE chain
    shielded.injection_score # float in [0, 1] (None if classifier disabled)
    shielded.changes         # list[str] of transformations applied
"""
from .pipeline import process, ShieldedInput
from .canonicaliser import canonicalise, CanonicalisedSpan
from .provenance import wrap_untrusted, UNTRUSTED_OPEN_RE, UNTRUSTED_CLOSE_RE
from .secret_scrub import scrub, rehydrate
from .chain import HashChain, append_to_default_chain
from .taint_vault import TaintVault, TaintEntry, TrustLevel, LaunderingReport
from .definitional_drift import (
    DefinitionalDriftDetector,
    DefinitionFingerprint,
    DefinitionExtraction,
    DriftFinding,
    structural_extractor,
    jaccard_divergence,
    cosine_divergence,
)

__all__ = [
    "process",
    "ShieldedInput",
    "canonicalise",
    "CanonicalisedSpan",
    "wrap_untrusted",
    "UNTRUSTED_OPEN_RE",
    "UNTRUSTED_CLOSE_RE",
    "scrub",
    "rehydrate",
    "HashChain",
    "append_to_default_chain",
    "TaintVault",
    "TaintEntry",
    "TrustLevel",
    "LaunderingReport",
    "DefinitionalDriftDetector",
    "DefinitionFingerprint",
    "DefinitionExtraction",
    "DriftFinding",
    "structural_extractor",
    "jaccard_divergence",
    "cosine_divergence",
]

__version__ = "0.2.0"
