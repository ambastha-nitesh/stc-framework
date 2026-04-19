"""Optional Flask service facade for the STC Framework.

Install with ``pip install stc-framework[service]``.
"""

from stc_framework.service.app import create_app

__all__ = ["create_app"]
