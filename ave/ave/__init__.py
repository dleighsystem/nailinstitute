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

    >>> from ave.scoring import compute_avss, AVSSVector
    >>> score = compute_avss(AVSSVector(attack_vector=AttackVector.NETWORK))

    >>> from ave.export import export_database
    >>> export_database(ave.all_cards(), "./ave-database")

Built from empirical research: 29 experiments, 50,000+ adversarial
simulations at the NAIL Institute (Neuravant AI Limited).
"""

__version__ = "1.1.0"

from .schema import (
    AVECard,
    Category,
    Severity,
    Status,
    EnvironmentVector,
    Defence,
    Evidence,
)

from .scoring import (
    AVSSVector,
    AVSSScore,
    AttackVector,
    AttackComplexity,
    PrivilegesRequired,
    UserInteraction,
    ScopeChange,
    Impact,
    TemporalExploitability,
    AgenticExploitability,
    compute_avss,
    critical_network_agent,
    medium_local_single,
)

from .poc import (
    ProofOfConcept,
    PoCType,
    PoCStatus,
    PoCEnvironment,
    PoCScript,
    PoCLog,
    PoCPrompt,
)

from .timeline import (
    CardTimeline,
    TimelineEvent,
    LifecycleStage,
)

from .export import (
    card_to_json,
    card_to_markdown,
    export_database,
    generate_index_table,
    generate_severity_index,
)

from .registry import (
    lookup,
    search,
    all_cards,
    cards_by_severity,
    cards_by_category,
    cards_by_status,
    card_count,
    next_id,
    submit_card,
    submit_draft,
    retract_card,
    reset_dynamic,
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
    # Scoring (AVSS)
    "AVSSVector",
    "AVSSScore",
    "AttackVector",
    "AttackComplexity",
    "PrivilegesRequired",
    "UserInteraction",
    "ScopeChange",
    "Impact",
    "TemporalExploitability",
    "AgenticExploitability",
    "compute_avss",
    "critical_network_agent",
    "medium_local_single",
    # PoC
    "ProofOfConcept",
    "PoCType",
    "PoCStatus",
    "PoCEnvironment",
    "PoCScript",
    "PoCLog",
    "PoCPrompt",
    # Timeline
    "CardTimeline",
    "TimelineEvent",
    "LifecycleStage",
    # Export
    "card_to_json",
    "card_to_markdown",
    "export_database",
    "generate_index_table",
    "generate_severity_index",
    # Registry
    "lookup",
    "search",
    "all_cards",
    "cards_by_severity",
    "cards_by_category",
    "cards_by_status",
    "card_count",
    # Live Registry
    "next_id",
    "submit_card",
    "submit_draft",
    "retract_card",
    "reset_dynamic",
]
