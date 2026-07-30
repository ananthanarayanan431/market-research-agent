"""Service layer: business logic sitting between `api/v1/` routers and `repository/`/the graph.

Each service is constructed once in `main.py`'s lifespan (with its `repository/` and graph
dependencies injected) and attached to `app.state`; routers only extract request data, call a
service method, and map the result onto an HTTP response.
"""
