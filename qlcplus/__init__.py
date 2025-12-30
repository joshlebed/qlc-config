"""
QLC+ WebSocket Client Library

A Python library for controlling QLC+ lighting software via WebSocket API.
"""

from .client import QLCPlusClient, QLCPlusError

__version__ = "0.1.0"
__all__ = ["QLCPlusClient", "QLCPlusError"]
