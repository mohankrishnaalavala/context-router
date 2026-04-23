"""Packaged runtime assets bundled with the context-router CLI wheel.

The ``graph`` command reads ``d3.v7.min.js`` from this package via
``importlib.resources`` so the generated ``graph.html`` is fully
self-contained and renders without network access (e.g. offline,
behind a firewall, or under a strict CSP).
"""
