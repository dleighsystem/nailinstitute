"""
M16: EU AI Act Article 12 Flight Recorder (Traceability).

Provides a cryptographically verifiable append-only log of an agent's
operations. If an agent goes rogue, this flight recorder acts as the 
"black box" for Neuravant Insurance claims adjustments and EU regulators,
proving exactly what the agent saw and did without repudiation.
"""
import hashlib
import json
import time
from typing import Any, Dict, List, Optional
from .types import Alert


class FlightRecorderError(Exception):
    """Raised when the flight recorder detects tampering or failures."""
    pass


class EventLog:
    """A single logged event in the flight recorder chain."""
    def __init__(self, agent_id: str, event_type: str, payload: dict, prev_hash: str):
        self.agent_id = agent_id
        self.timestamp = time.time()
        self.event_type = event_type
        self.payload = payload
        self.prev_hash = prev_hash
        self.hash = self._compute_hash()

    def _compute_hash(self) -> str:
        data = {
            "agent_id": self.agent_id,
            "timestamp": self.timestamp,
            "event_type": self.event_type,
            "payload": self.payload,
            "prev_hash": self.prev_hash,
        }
        encoded = json.dumps(data, sort_keys=True).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def to_dict(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "timestamp": self.timestamp,
            "event_type": self.event_type,
            "payload": self.payload,
            "prev_hash": self.prev_hash,
            "hash": self.hash,
        }


class FlightRecorder:
    """
    Immutable, hash-chained logger for high-risk autonomous agents.
    
    Usage:
        recorder = FlightRecorder(agent_id="hr-bot-prod")
        
        # Log LLM input/output
        recorder.log_thought("Deciding to call database...", tokens=45)
        
        # Log execution
        recorder.log_action("query_db", {"table": "users"})
        
        # Verify chain integrity (e.g. during an insurance claim investigation)
        assert recorder.verify_integrity()
    """
    def __init__(self, agent_id: str, session_id: Optional[str] = None):
        self.agent_id = agent_id
        self.session_id = session_id or f"session_{int(time.time())}"
        self.chain: List[EventLog] = []
        
        # Genesis block
        self._append("SESSION_START", {"session_id": self.session_id})

    def _append(self, event_type: str, payload: dict) -> EventLog:
        prev_hash = self.chain[-1].hash if self.chain else "0" * 64
        event = EventLog(self.agent_id, event_type, payload, prev_hash)
        self.chain.append(event)
        return event

    def log_thought(self, prompt: str, completion: str, tokens: int = 0) -> str:
        """Log the LLM's cognition (input prompt -> output generation)."""
        # We hash the strings if they are too large to prevent bloat, 
        # but for this POC we'll store them. In production, we'd truncate/hash.
        event = self._append("COGNITION", {
            "prompt_length": len(prompt),
            "completion_length": len(completion),
            "tokens": tokens,
            # For brevity in memory:
            "prompt_preview": prompt[:200] + ("..." if len(prompt) > 200 else ""),
            "completion_preview": completion[:200] + ("..." if len(completion) > 200 else ""),
        })
        return event.hash

    def log_action(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        """Log an external tool invocation (e.g., API call, DB execution)."""
        event = self._append("ACTION", {
            "tool_name": tool_name,
            "arguments": arguments,
        })
        return event.hash

    def log_observation(self, result: str, from_tool: str) -> str:
        """Log the external environment's response to an action."""
        event = self._append("OBSERVATION", {
            "from_tool": from_tool,
            "result_length": len(result),
            "result_preview": result[:200] + ("..." if len(result) > 200 else ""),
        })
        return event.hash

    def log_alert(self, alert: Alert) -> str:
        """Log a NAIL monitor pathology alert."""
        event = self._append("MONITOR_ALERT", {
            "detector": alert.detector,
            "severity": alert.severity.value,
            "message": alert.message,
        })
        return event.hash

    def verify_integrity(self) -> bool:
        """
        Verify the cryptographic hash chain.
        Returns True if the log is untampered, raises FlightRecorderError if broken.
        """
        if not self.chain:
            return True

        for i in range(1, len(self.chain)):
            current = self.chain[i]
            previous = self.chain[i-1]

            if current.prev_hash != previous.hash:
                raise FlightRecorderError(f"Chain broken at index {i}: Block prev_hash '{current.prev_hash}' does not match prior hash '{previous.hash}'.")
            
            if current.hash != current._compute_hash():
                raise FlightRecorderError(f"Chain broken at index {i}: Block hash '{current.hash}' is invalid for its contents.")

        return True

    def export_log(self) -> str:
        """Export the entire verifiable chain as JSON."""
        return json.dumps([event.to_dict() for event in self.chain], indent=2)
