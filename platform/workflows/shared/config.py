"""Configuration for workflows service."""

import os

# Database
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "postgres")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
POSTGRES_DB = os.getenv("POSTGRES_DB", "evoiot")
POSTGRES_USER = os.getenv("POSTGRES_USER", "postgres")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "postgres")

POSTGRES_URL = f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"

# LLM - Volcengine Doubao (OpenAI-compatible)
LLM_MODEL = os.getenv("LLM_MODEL", "openai/doubao-seed-2.0-code")
LLM_API_BASE = os.getenv("LLM_API_BASE", "https://ark.cn-beijing.volces.com/api/coding/v3")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")

# Restate
RESTATE_INGRESS_URL = os.getenv("RESTATE_INGRESS_URL", "http://restate:8080")
