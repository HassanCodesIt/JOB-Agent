"""Native LinkedIn Job Finder integration for AI Job Assistant.

The scraper under ``BrowserAutomationForLinkdin`` keeps its own Playwright/CDP
lifecycle and JSON persistence. This package is the thin integration layer that
launches it as a subprocess, imports its run files, filters the imported jobs
with a minimal-token classifier and hands accepted jobs to the existing
AI Job Assistant application pipeline.
"""

__all__ = [
    "filter_service",
    "importer",
    "modes",
    "prompt_service",
    "runner",
    "url_utils",
]
