"""Versioned HTTP surface for the market-research agent (FastAPI routers).

The app itself (lifespan, middleware, exception handlers) lives in `agentdrops.main`;
this package holds only the versioned routers it mounts, one subpackage per version.
"""
