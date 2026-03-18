"""
AVE — Agentic Vulnerabilities & Exposures
============================================
The CVE database for AI agent failures.

Every vulnerability that can affect an autonomous AI agent — from prompt
injection to consensus paralysis to memory laundering — gets a unique
AVE-ID, a severity score, a proof-of-concept reference, and a mapping
to known defences.

This is the MITRE ATT&CK of the Agentic Era.

Usage:
    >>> import ave
    >>> ave.lookup("AVE-2025-0001")
    AVECard(ave_id='AVE-2025-0001', name='Sleeper Payload Injection', ...)

    >>> ave.search(category=Category.MEMORY)
    [AVECard(...), AVECard(...), ...]

    >>> ave.all_cards()
    [AVECard(...), ... ]  # All 29+ cards

    >>> for card in ave.cards_by_severity(Severity.CRITICAL):
    ...     print(card.ave_id, card.name)

Built from empirical research: 29 experiments, 50,000+ adversarial
simulations at the NAIL Institute (Neuravant AI Limited).
"""

__version__ = "1.0.0"

from .schema import (
    AVECard,
    Category,
    Severity,
    Status,
    EnvironmentVector,
    Defence,
    Evidence,
)

from .registry import (
    lookup,
    search,
    all_cards,
    cards_by_severity,
    cards_by_category,
    cards_by_status,
    card_count,
)

__all__ = [
    # Schema
    "AVECard",
    "Category",
    "Severity",
    "Status",
    "EnvironmentVector",
    "Defence",
    "Evidence",
    # Registry
    "lookup",
    "search",
    "all_cards",
    "cards_by_severity",
    "cards_by_category",
    "cards_by_status",
    "card_count",
]
