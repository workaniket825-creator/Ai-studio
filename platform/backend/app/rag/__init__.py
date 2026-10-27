"""RAG / Knowledge Pipelines — isolated, additive module (feature-flagged, off by default).

A Pipeline is a first-class configurable object: sources -> (extract -> clean -> chunk) ->
embed -> index (vector store) -> retrieve. Consumed by Chat and by agents (search_knowledge
tool). Provider-backed stages (embeddings/ocr/multimodal) select an existing Model Endpoint by
capability type — no separate credential store.

Sandbox note: local embeddings + a JSON-backed vector store are used when heavy deps
(sentence-transformers, psycopg/pgvector) aren't installed, so the full pipeline is verifiable
offline. The pgvector + API-embedding paths are wired and guarded for production.
"""
