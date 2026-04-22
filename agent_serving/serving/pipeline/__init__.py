"""Pipeline orchestration — pluggable search pipeline.

Stages: Normalizer → QueryPlanner → RetrieverManager → Fusion → Reranker → Assembler
Each stage has an abstract interface and a default implementation.
LLM-backed providers can be plugged in for any stage.
"""
