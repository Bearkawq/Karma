"""Prediction Engine - Predictive cognition layer for Karma.

Monitors predictions about system behavior and triggers reasoning when
predictions mismatch observations. This enables proactive rather than
reactive reasoning.

Key concepts:
- Predictions: Expected future states/outcomes
- Observations: Actual results compared against predictions
- Mismatch: Significant deviation requiring reasoning
- Reasoning trigger: Callback when prediction confidence is low
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from collections import deque
from threading import Lock
from enum import Enum


class PredictionDomain(Enum):
    """Domains for predictions."""
    TOOL_OUTCOME = "tool_outcome"
    AGENT_STATE = "agent_state"
    USER_ACTION = "user_action"
    SYSTEM_BEHAVIOR = "system_behavior"
    MODEL_RESPONSE = "model_response"
    WORKER_HEALTH = "worker_health"


class MismatchSeverity(Enum):
    """Severity of prediction mismatch."""
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class Prediction:
    """A single prediction about future state."""
    prediction_id: str
    domain: PredictionDomain
    target: str
    expected: Any
    confidence: float
    created_at: str
    expires_at: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Observation:
    """Actual observation to compare against prediction."""
    observation_id: str
    prediction_id: str
    actual: Any
    observed_at: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MismatchEvent:
    """Event when prediction mismatches observation."""
    mismatch_id: str
    prediction_id: str
    domain: PredictionDomain
    expected: Any
    actual: any
    deviation: float
    severity: MismatchSeverity
    triggered_reasoning: bool
    timestamp: str
    reasoning_triggered: Optional[str] = None


@dataclass
class PredictionStats:
    """Statistics for a prediction domain."""
    total_predictions: int = 0
    resolved_predictions: int = 0
    mismatches: int = 0
    average_deviation: float = 0.0
    accuracy_rate: float = 0.0


class PredictionEngine:
    """Predictive cognition layer - triggers reasoning on prediction failures.
    
    Usage:
        engine = PredictionEngine(base_dir)
        engine.register_reasoning_callback(my_reasoning_handler)
        
        # Make predictions
        pred_id = engine.predict(
            domain=PredictionDomain.TOOL_OUTCOME,
            target="tool:bash",
            expected="success",
            confidence=0.8,
            ttl_seconds=30,
        )
        
        # Later, record observation
        engine.observe(pred_id, "success")
    """

    DEFAULT_MISMATCH_THRESHOLDS = {
        MismatchSeverity.LOW: 0.1,
        MismatchSeverity.MEDIUM: 0.3,
        MismatchSeverity.HIGH: 0.5,
        MismatchSeverity.CRITICAL: 0.8,
    }

    def __init__(
        self,
        base_dir: str,
        mismatch_callback: Optional[Callable[[MismatchEvent], None]] = None,
        default_ttl_seconds: int = 60,
        max_pending_predictions: int = 1000,
    ):
        self._base_dir = Path(base_dir)
        self._base_dir.mkdir(parents=True, exist_ok=True)

        self._reasoning_callback = mismatch_callback
        self._default_ttl = default_ttl_seconds
        self._max_pending = max_pending_predictions

        self._predictions: Dict[str, Prediction] = {}
        self._observations: Dict[str, Observation] = {}
        self._mismatch_history: deque = deque(maxlen=500)

        self._domain_stats: Dict[PredictionDomain, PredictionStats] = {
            d: PredictionStats() for d in PredictionDomain
        }

        self._lock = Lock()

        self._load_state()

    def _state_path(self) -> Path:
        return self._base_dir / "data" / "prediction_engine.json"

    def _load_state(self):
        """Load persisted state."""
        p = self._state_path()
        if p.exists():
            try:
                data = json.loads(p.read_text())

                for pdata in data.get("predictions", []):
                    domain = PredictionDomain(pdata["domain"])
                    self._predictions[pdata["prediction_id"]] = Prediction(
                        prediction_id=pdata["prediction_id"],
                        domain=domain,
                        target=pdata["target"],
                        expected=pdata["expected"],
                        confidence=pdata["confidence"],
                        created_at=pdata["created_at"],
                        expires_at=pdata["expires_at"],
                        metadata=pdata.get("metadata", {}),
                    )

                for m in data.get("mismatch_history", []):
                    domain = PredictionDomain(m["domain"])
                    self._mismatch_history.append(MismatchEvent(
                        mismatch_id=m["mismatch_id"],
                        prediction_id=m["prediction_id"],
                        domain=domain,
                        expected=m["expected"],
                        actual=m["actual"],
                        deviation=m["deviation"],
                        severity=MismatchSeverity(m["severity"]),
                        triggered_reasoning=m["triggered_reasoning"],
                        timestamp=m["timestamp"],
                        reasoning_triggered=m.get("reasoning_triggered"),
                    ))

            except Exception:
                pass

    def _save_state(self):
        """Persist state."""
        p = self._state_path()
        p.parent.mkdir(parents=True, exist_ok=True)

        predictions_data = [
            {
                "prediction_id": p.prediction_id,
                "domain": p.domain.value,
                "target": p.target,
                "expected": p.expected,
                "confidence": p.confidence,
                "created_at": p.created_at,
                "expires_at": p.expires_at,
                "metadata": p.metadata,
            }
            for p in self._predictions.values()
        ]

        mismatch_data = [
            {
                "mismatch_id": m.mismatch_id,
                "prediction_id": m.prediction_id,
                "domain": m.domain.value,
                "expected": m.expected,
                "actual": m.actual,
                "deviation": m.deviation,
                "severity": m.severity.value,
                "triggered_reasoning": m.triggered_reasoning,
                "timestamp": m.timestamp,
                "reasoning_triggered": m.reasoning_triggered,
            }
            for m in self._mismatch_history
        ]

        p.write_text(json.dumps({
            "predictions": predictions_data,
            "mismatch_history": mismatch_data,
        }, indent=2, default=str))

    def register_reasoning_callback(
        self,
        callback: Callable[[MismatchEvent], None]
    ) -> None:
        """Register callback for reasoning triggers."""
        self._reasoning_callback = callback

    def predict(
        self,
        domain: PredictionDomain,
        target: str,
        expected: Any,
        confidence: float,
        ttl_seconds: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Make a prediction about future state.
        
        Args:
            domain: Domain of prediction
            target: What we're predicting about (e.g., "tool:bash", "user:intent")
            expected: Expected outcome/value
            confidence: Confidence in prediction (0-1)
            ttl_seconds: How long to wait for observation
            metadata: Additional context
            
        Returns:
            Prediction ID for later observation
        """
        from uuid import uuid4

        ttl = ttl_seconds or self._default_ttl
        now = datetime.now()

        pred_id = str(uuid4())[:12]
        prediction = Prediction(
            prediction_id=pred_id,
            domain=domain,
            target=target,
            expected=expected,
            confidence=confidence,
            created_at=now.isoformat(),
            expires_at=(now + timedelta(seconds=ttl)).isoformat(),
            metadata=metadata or {},
        )

        with self._lock:
            # Cleanup expired predictions if at capacity
            self._cleanup_expired()

            if len(self._predictions) >= self._max_pending:
                self._cleanup_expired()

            self._predictions[pred_id] = prediction

            stats = self._domain_stats[domain]
            stats.total_predictions += 1

        return pred_id

    def observe(
        self,
        prediction_id: str,
        actual: Any,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[MismatchEvent]:
        """Record observation and check for mismatch.
        
        Args:
            prediction_id: ID returned from predict()
            actual: Actual observed value
            metadata: Additional context
            
        Returns:
            MismatchEvent if mismatch detected, None otherwise
        """
        from uuid import uuid4

        with self._lock:
            prediction = self._predictions.get(prediction_id)
            if not prediction:
                return None

            obs_id = str(uuid4())[:12]
            observation = Observation(
                observation_id=obs_id,
                prediction_id=prediction_id,
                actual=actual,
                observed_at=datetime.now().isoformat(),
                metadata=metadata or {},
            )

            self._observations[obs_id] = observation

            mismatch = self._check_mismatch(prediction, observation)

            if mismatch:
                self._mismatch_history.append(mismatch)
                stats = self._domain_stats[prediction.domain]
                stats.mismatches += 1
                stats.resolved_predictions += 1

                if mismatch.triggered_reasoning and self._reasoning_callback:
                    try:
                        self._reasoning_callback(mismatch)
                    except Exception:
                        pass

            # Remove resolved prediction
            del self._predictions[prediction_id]

            self._update_stats(prediction.domain)
            self._save_state()

            return mismatch

    def _check_mismatch(
        self,
        prediction: Prediction,
        observation: Observation,
    ) -> Optional[MismatchEvent]:
        """Check if observation mismatches prediction."""
        from uuid import uuid4

        expected = prediction.expected
        actual = observation.actual

        # Calculate deviation
        deviation = self._calculate_deviation(expected, actual)

        # Determine severity based on confidence and deviation
        severity = self._classify_severity(
            expected, actual, deviation, prediction.confidence
        )

        # Trigger reasoning if significant mismatch
        trigger_reasoning = severity in (
            MismatchSeverity.HIGH,
            MismatchSeverity.CRITICAL,
        )

        if severity == MismatchSeverity.NONE:
            return None

        return MismatchEvent(
            mismatch_id=str(uuid4())[:12],
            prediction_id=prediction.prediction_id,
            domain=prediction.domain,
            expected=expected,
            actual=actual,
            deviation=deviation,
            severity=severity,
            triggered_reasoning=trigger_reasoning,
            timestamp=datetime.now().isoformat(),
        )

    def _calculate_deviation(self, expected: Any, actual: Any) -> float:
        """Calculate deviation between expected and actual."""
        # Numeric deviation
        if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
            if expected == 0:
                return 1.0 if actual != 0 else 0.0
            return min(1.0, abs(actual - expected) / abs(expected))

        # Boolean deviation
        if isinstance(expected, bool) and isinstance(actual, bool):
            return 1.0 if expected != actual else 0.0

        # String deviation (simple containment check)
        if isinstance(expected, str) and isinstance(actual, str):
            if expected.lower() == actual.lower():
                return 0.0
            if expected.lower() in actual.lower() or actual.lower() in expected.lower():
                return 0.3
            return 1.0

        # List/set deviation
        if isinstance(expected, (list, set)) and isinstance(actual, (list, set)):
            if not expected:
                return 0.0 if not actual else 1.0
            matching = len(set(expected) & set(actual))
            return 1.0 - (matching / max(len(expected), len(actual), 1))

        # Generic equality check
        return 0.0 if expected == actual else 1.0

    def _classify_severity(
        self,
        expected: Any,
        actual: Any,
        deviation: float,
        confidence: float,
    ) -> MismatchSeverity:
        """Classify mismatch severity."""
        if deviation == 0.0:
            return MismatchSeverity.NONE

        # Adjust threshold based on prediction confidence
        # High confidence predictions have lower mismatch tolerance
        confidence_adjustment = (1.0 - confidence) * 0.2

        effective_threshold = 0.1 + confidence_adjustment

        if deviation < effective_threshold + 0.1:
            return MismatchSeverity.LOW
        elif deviation < effective_threshold + 0.3:
            return MismatchSeverity.MEDIUM
        elif deviation < effective_threshold + 0.5:
            return MismatchSeverity.HIGH
        else:
            return MismatchSeverity.CRITICAL

    def _cleanup_expired(self):
        """Remove expired predictions."""
        now = datetime.now()
        expired = [
            pid for pid, pred in self._predictions.items()
            if datetime.fromisoformat(pred.expires_at) < now
        ]
        for pid in expired:
            stats = self._predictions[pid].domain
            self._domain_stats[stats].resolved_predictions += 1
            del self._predictions[pid]

    def _update_stats(self, domain: PredictionDomain):
        """Update domain statistics."""
        stats = self._domain_stats[domain]
        if stats.resolved_predictions > 0:
            stats.accuracy_rate = 1.0 - (stats.mismatches / stats.resolved_predictions)

        # Calculate average deviation from recent mismatches
        recent_mismatches = [
            m for m in self._mismatch_history
            if m.domain == domain
        ][-20:]
        if recent_mismatches:
            stats.average_deviation = sum(m.deviation for m in recent_mismatches) / len(recent_mismatches)

    def get_pending_predictions(
        self,
        domain: Optional[PredictionDomain] = None,
    ) -> List[Prediction]:
        """Get pending predictions, optionally filtered by domain."""
        with self._lock:
            preds = list(self._predictions.values())
            if domain:
                preds = [p for p in preds if p.domain == domain]
            return preds

    def get_mismatch_history(
        self,
        domain: Optional[PredictionDomain] = None,
        limit: int = 50,
    ) -> List[MismatchEvent]:
        """Get recent mismatch events."""
        mismatches = list(self._mismatch_history)
        if domain:
            mismatches = [m for m in mismatches if m.domain == domain]
        return mismatches[-limit:]

    def get_domain_stats(self, domain: PredictionDomain) -> PredictionStats:
        """Get statistics for a domain."""
        return self._domain_stats[domain]

    def get_all_stats(self) -> Dict[str, PredictionStats]:
        """Get all domain statistics."""
        return {d.value: s for d, s in self._domain_stats.items()}

    def get_prediction_summary(self) -> Dict[str, Any]:
        """Get summary of prediction engine state."""
        total_pending = len(self._predictions)
        total_mismatches = len(self._mismatch_history)

        domain_summary = {}
        for domain, stats in self._domain_stats.items():
            domain_summary[domain.value] = {
                "total": stats.total_predictions,
                "resolved": stats.resolved_predictions,
                "mismatches": stats.mismatches,
                "accuracy_rate": stats.accuracy_rate,
                "pending": len([p for p in self._predictions.values() if p.domain == domain]),
            }

        return {
            "total_predictions": sum(s.total_predictions for s in self._domain_stats.values()),
            "pending_predictions": total_pending,
            "total_mismatches": total_mismatches,
            "by_domain": domain_summary,
            "reasoning_triggered": sum(1 for m in self._mismatch_history if m.triggered_reasoning),
        }

    def predict_and_observe(
        self,
        domain: PredictionDomain,
        target: str,
        expected: Any,
        actual: Any,
        confidence: float = 0.8,
        ttl_seconds: int = 30,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[MismatchEvent]:
        """Convenience method for immediate predict + observe.
        
        Useful for synchronous predictions where we know the outcome
        immediately after making the prediction.
        """
        pred_id = self.predict(
            domain=domain,
            target=target,
            expected=expected,
            confidence=confidence,
            ttl_seconds=ttl_seconds,
            metadata=metadata,
        )
        return self.observe(pred_id, actual, metadata)


_global_engine: Optional[PredictionEngine] = None


def get_prediction_engine(base_dir: str = ".") -> PredictionEngine:
    """Get global prediction engine instance."""
    global _global_engine
    if _global_engine is None:
        _global_engine = PredictionEngine(base_dir)
    return _global_engine


def set_prediction_engine(engine: PredictionEngine):
    """Set global prediction engine (for testing)."""
    global _global_engine
    _global_engine = engine
