"""Provider Health Monitor - Track research provider health.

Track for each research provider:
- success rate
- error rate
- last successful query
- deprioritization state
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field
from threading import Lock
from collections import deque


@dataclass
class ProviderHealth:
    """Health status for a single provider."""
    provider_name: str
    total_queries: int = 0
    successful_queries: int = 0
    failed_queries: int = 0
    last_success: Optional[str] = None
    last_failure: Optional[str] = None
    deprioritized: bool = False
    deprioritize_until: Optional[str] = None
    consecutive_failures: int = 0
    
    @property
    def success_rate(self) -> float:
        if self.total_queries == 0:
            return 1.0
        return self.successful_queries / self.total_queries
    
    @property
    def error_rate(self) -> float:
        if self.total_queries == 0:
            return 0.0
        return self.failed_queries / self.total_queries
    
    def should_deprioritize(self) -> bool:
        """Check if provider should be deprioritized."""
        if self.deprioritized and self.deprioritize_until:
            if datetime.fromisoformat(self.deprioritize_until) < datetime.now():
                self.deprioritized = False
                self.deprioritize_until = None
        return self.deprioritized


class ProviderHealthMonitor:
    """Monitors research provider health."""
    
    def __init__(
        self,
        failure_threshold: int = 3,
        deprioritize_duration_minutes: int = 5,
    ):
        self._providers: Dict[str, ProviderHealth] = {}
        self._lock = Lock()
        self._failure_threshold = failure_threshold
        self._deprioritize_duration = deprioritize_duration_minutes * 60
    
    def record_success(self, provider_name: str) -> None:
        """Record a successful query."""
        with self._lock:
            if provider_name not in self._providers:
                self._providers[provider_name] = ProviderHealth(provider_name)
            
            health = self._providers[provider_name]
            health.total_queries += 1
            health.successful_queries += 1
            health.last_success = datetime.now().isoformat()
            health.consecutive_failures = 0
            
            if health.deprioritized and health.success_rate > 0.7:
                health.deprioritized = False
                health.deprioritize_until = None
    
    def record_failure(self, provider_name: str, error: Optional[str] = None) -> None:
        """Record a failed query."""
        with self._lock:
            if provider_name not in self._providers:
                self._providers[provider_name] = ProviderHealth(provider_name)
            
            health = self._providers[provider_name]
            health.total_queries += 1
            health.failed_queries += 1
            health.last_failure = datetime.now().isoformat()
            health.consecutive_failures += 1
            
            if health.consecutive_failures >= self._failure_threshold:
                health.deprioritized = True
                health.deprioritize_until = (
                    datetime.now().timestamp() + self._deprioritize_duration
                )
    
    def get_health(self, provider_name: str) -> Optional[ProviderHealth]:
        """Get health for a specific provider."""
        with self._lock:
            return self._providers.get(provider_name)
    
    def get_all_health(self) -> List[Dict[str, Any]]:
        """Get health for all providers."""
        with self._lock:
            return [
                {
                    "provider_name": h.provider_name,
                    "total_queries": h.total_queries,
                    "successful_queries": h.successful_queries,
                    "failed_queries": h.failed_queries,
                    "success_rate": h.success_rate,
                    "error_rate": h.error_rate,
                    "last_success": h.last_success,
                    "last_failure": h.last_failure,
                    "deprioritized": h.deprioritized,
                    "deprioritize_until": h.deprioritize_until,
                    "consecutive_failures": h.consecutive_failures,
                }
                for h in self._providers.values()
            ]
    
    def get_working_providers(self) -> List[str]:
        """Get list of providers that are working (not deprioritized)."""
        with self._lock:
            return [
                h.provider_name for h in self._providers.values()
                if not h.should_deprioritize()
            ]
    
    def get_best_provider(self) -> Optional[str]:
        """Get the provider with highest success rate."""
        with self._lock:
            if not self._providers:
                return None
            
            working = [
                h for h in self._providers.values()
                if not h.should_deprioritize()
            ]
            
            if not working:
                return None
            
            return max(working, key=lambda h: h.success_rate).provider_name
    
    def reset_provider(self, provider_name: str) -> None:
        """Reset a provider's health status."""
        with self._lock:
            if provider_name in self._providers:
                health = self._providers[provider_name]
                health.deprioritized = False
                health.deprioritize_until = None
                health.consecutive_failures = 0
    
    def get_summary(self) -> Dict[str, Any]:
        """Get provider health summary."""
        with self._lock:
            total_providers = len(self._providers)
            healthy = sum(1 for h in self._providers.values() if h.success_rate > 0.7)
            deprioritized = sum(1 for h in self._providers.values() if h.deprioritized)
            
            return {
                "total_providers": total_providers,
                "healthy": healthy,
                "deprioritized": deprioritized,
                "providers": self.get_all_health(),
            }
    
    def save_health(self, path: str) -> None:
        """Persist provider health to file."""
        with self._lock:
            health_data = self.get_all_health()
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w") as f:
            json.dump(health_data, f, indent=2)
    
    def clear(self) -> None:
        """Clear all provider health data (for testing)."""
        with self._lock:
            self._providers.clear()


_global_monitor: Optional[ProviderHealthMonitor] = None


def get_provider_health_monitor() -> ProviderHealthMonitor:
    """Get global provider health monitor."""
    global _global_monitor
    if _global_monitor is None:
        _global_monitor = ProviderHealthMonitor()
    return _global_monitor
