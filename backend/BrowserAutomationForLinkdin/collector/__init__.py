"""LinkedIn job-post collector.

Attaches to an already-open, logged-in Chrome over CDP, searches LinkedIn Posts
for AI/ML roles and prints only posts that look like real job opportunities and
contain at least one e-mail address. The browser and session are never closed.
"""

__version__ = "1.0.0"

__all__ = ["__version__"]