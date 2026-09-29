"""USHMA -- Urban System for Heat-stress Monitoring & Alerting.

An impact-based heat-health early warning system: it forecasts not what the
weather will be, but what the weather will do to people.
"""

__version__ = "0.1.0"

from ushma.config import settings

__all__ = ["settings", "__version__"]
