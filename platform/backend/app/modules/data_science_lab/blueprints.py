"""NVIDIA Blueprints — external reference catalog (spec §9).

These are EXTERNAL reference workflows (build.nvidia.com/blueprints, NVIDIA-AI-Blueprints
on GitHub), distinct from internal Notebook Templates (§8). We only surface links; an
associate clones a repo into a lab runtime to try it. Verify licence/availability at
build.nvidia.com before recommending — the catalog changes frequently.
"""
from __future__ import annotations

BLUEPRINTS = [
    {"name": "RAG (Retrieval-Augmented Generation)",
     "summary": "Reference multimodal RAG pipeline with NIM microservices.",
     "docs": "https://build.nvidia.com/nvidia/build-an-enterprise-rag-pipeline",
     "repo": "https://github.com/NVIDIA-AI-Blueprints/rag", "category": "agentic"},
    {"name": "AI Virtual Assistant",
     "summary": "Customer-service assistant blueprint (agents + RAG).",
     "docs": "https://build.nvidia.com/nvidia/ai-virtual-assistant-for-customer-service",
     "repo": "https://github.com/NVIDIA-AI-Blueprints/ai-virtual-assistant", "category": "agentic"},
    {"name": "Video Search & Summarization",
     "summary": "Video-analytics agent blueprint.",
     "docs": "https://build.nvidia.com/nvidia/video-search-and-summarization",
     "repo": "https://github.com/NVIDIA-AI-Blueprints/video-search-and-summarization", "category": "agentic"},
    {"name": "Digital Human",
     "summary": "Interactive avatar blueprint (ACE + NIM).",
     "docs": "https://build.nvidia.com/nvidia/digital-humans-for-customer-service",
     "repo": "https://github.com/NVIDIA-AI-Blueprints/digital-human", "category": "generative"},
    {"name": "PDF to Podcast",
     "summary": "Document-to-audio generative blueprint.",
     "docs": "https://build.nvidia.com/nvidia/pdf-to-podcast",
     "repo": "https://github.com/NVIDIA-AI-Blueprints/pdf-to-podcast", "category": "generative"},
]


def list_blueprints() -> list[dict]:
    return BLUEPRINTS
