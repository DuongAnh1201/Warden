"""Concrete tools the agents call to act in the real world.

Some tools touch macOS-native surfaces (Messages, Contacts), some call cloud APIs
(Resend for email, Google Calendar), and some are local (knowledge base). To keep
the assistant runnable in CI, on non-macOS machines, and in the hosted "Try as
Guest" demo, every such tool checks :data:`DEMO_MODE` and simulates the action
instead of performing it.

Set ``DESIR_DEMO=0`` in the environment to perform real actions.
"""
import os
import sys

from dotenv import load_dotenv

# Load .env here too: DEMO_MODE is read at import time, and if this module is
# imported before config.load_dotenv() runs, DESIR_DEMO from .env would be missed
# and demo mode would wrongly default to on. load_dotenv() is idempotent.
load_dotenv()

DEMO_MODE: bool = os.getenv("DESIR_DEMO", "1") not in ("0", "false", "False", "")
"""When True (the default), real-world tools simulate instead of acting."""

IS_MACOS: bool = sys.platform == "darwin"
"""macOS-native tools (Messages/Contacts) only work when this is True."""
