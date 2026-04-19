"""Gunicorn entrypoint for the STC Framework service.

Run with::

    gunicorn -k gthread --threads 8 -w 4 \
        --bind 0.0.0.0:8000 \
        "stc_framework.service.wsgi:application"

We deliberately use threaded workers (not ``gevent``) because the
:class:`_SystemRunner` inside the Flask app owns a dedicated asyncio event
loop; all long I/O happens in that loop so Flask's request threads only
wait on futures.
"""

from __future__ import annotations

from stc_framework.service.app import create_app

application = create_app()
