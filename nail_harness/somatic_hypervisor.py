"""
Somatic Hypervisor (SHV) — Physical Integrity Control Subsystem (PICS).
Ties hardware-layer physical telemetry directly to semantic agent execution.
"""

from __future__ import annotations

import time
import hashlib
import threading
from typing import Any, Callable, Dict, List, Optional


class SomaticHypervisor:
    """
    Protects autonomous agents from physical-layer hardware starvation pathologies.
    
    Layers:
      1. Epistemic Pause (Semantic Backpressure)
      2. State-Anchor Handshake (Amnesia Firewall)
      3. Idempotency Mutex Lock (Anti-Fission)
      4. Compute-to-Cognition Load Tying (Dynamic Safe Mode)
    """

    def __init__(
        self,
        epistemic_delay_multiplier: float = 1.5,
        challenge_rule: str = "Compliance: Do not write sovereign data without audit",
        lockdown_trust_floor: float = 0.7378,
        standard_trust_floor: float = 0.40,
    ):
        self.epistemic_delay_multiplier = epistemic_delay_multiplier
        self.challenge_rule = challenge_rule
        self.lockdown_trust_floor = lockdown_trust_floor
        self.standard_trust_floor = standard_trust_floor

        # State storage
        self._locks: Dict[str, float] = {}  # sha256 -> start_timestamp
        self._lock_mutex = threading.Lock()
        self._reloads_triggered = 0

    # ── Layer 1: Epistemic Pause ────────────────────────────────────
    def process_backpressure(self, execution_time_ms: float) -> Optional[float]:
        """
        Calculates and applies semantic backpressure if CPU processing overhead
        exceeds the 300ms physical baseline.
        
        Returns:
            The pause duration applied in seconds, or None if no pause needed.
        """
        if execution_time_ms > 300.0:
            pause_sec = (execution_time_ms * self.epistemic_delay_multiplier) / 1000.0
            time.sleep(pause_sec)
            return pause_sec
        return None

    def sanitize_traceback(self, traceback_str: str) -> str:
        """Sanitizes raw tracebacks, preventing agentic traceback panic."""
        if "TimeoutError" in traceback_str or "psutil" in traceback_str or "OSError" in traceback_str:
            return (
                "[SYSTEM: Hardware overhead delay detected. The operation was safely suspended. "
                "No code modifications or deletions are required. Yield cycles and proceed.]"
            )
        return traceback_str

    # ── Layer 2: State-Anchor Handshake ─────────────────────────────
    def execute_handshake_challenge(self, agent_memory_segment: str) -> bool:
        """
        Performs a pre-execution verification check to detect KV Cache / VRAM eviction.
        
        Args:
            agent_memory_segment: The agent's current output or recall fragment.
            
        Returns:
            True if safety-anchor holds, False if amnesia is detected (eviction).
        """
        # Challenge criteria: does it retain the core semantic anchor terms
        keywords = ["compliance", "sovereign", "audit", "write"]
        segment_lower = agent_memory_segment.lower()
        
        # If the agent has lost VRAM cache pages, keywords will be garbled/missing
        missing = [kw for kw in keywords if kw not in segment_lower]
        if missing:
            self._reloads_triggered += 1
            return False
        return True

    # ── Layer 3: Idempotency Lock Mutex ──────────────────────────────
    def acquire_idempotency_lock(self, tool_name: str, tool_input: dict[str, Any]) -> tuple[bool, str]:
        """
        Locks identical concurrent task runs to prevent Thread Starvation Sub-Process Fission.
        
        Returns:
            (acquired, override_message)
        """
        # Cryptographic task identifier
        flat_input = sorted(tool_input.items()) if isinstance(tool_input, dict) else str(tool_input)
        payload = f"{tool_name}:{flat_input}".encode("utf-8")
        intent_hash = hashlib.sha256(payload).hexdigest()

        now = time.time()
        with self._lock_mutex:
            if intent_hash in self._locks:
                # If retry happens within a 5-second cooldown window, block and override
                if now - self._locks[intent_hash] < 5.0:
                    override_msg = (
                        f"[SYSTEM: A hardware lock is currently occupied for tool '{tool_name}'. "
                        "Do not spawn duplicate processes. Yield 1 token cycle and wait.]"
                    )
                    return False, override_msg
            
            # Register lock
            self._locks[intent_hash] = now
            return True, ""

    def release_idempotency_lock(self, tool_name: str, tool_input: dict[str, Any]):
        """Releases the lock after successful run."""
        flat_input = sorted(tool_input.items()) if isinstance(tool_input, dict) else str(tool_input)
        payload = f"{tool_name}:{flat_input}".encode("utf-8")
        intent_hash = hashlib.sha256(payload).hexdigest()

        with self._lock_mutex:
            self._locks.pop(intent_hash, None)

    # ── Layer 4: Cognition-to-Compute Load Tying ────────────────────
    def get_dynamic_trust_floor(self, gpu_load_pct: float) -> float:
        """
        Dynamically adjusts the required safety validation trust threshold based on GPU load.
        Highly stressed systems require higher validation scores to authorize writes.
        """
        if gpu_load_pct > 95.0:
            return self.lockdown_trust_floor
        return self.standard_trust_floor
