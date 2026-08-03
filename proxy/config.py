"""Configuration for Claude Max Proxy."""

from pathlib import Path

# Server
HOST = "127.0.0.1"
PORT = 8082

# OAuth endpoints
AUTH_AUTHORIZE_URL = "https://claude.ai/oauth/authorize"
AUTH_TOKEN_URL = "https://console.anthropic.com/v1/oauth/token"
CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
REDIRECT_URI = "https://console.anthropic.com/oauth/code/callback"
SCOPES = "org:create_api_key user:profile user:inference"

# Anthropic API
API_BASE = "https://api.anthropic.com"
ANTHROPIC_VERSION = "2023-06-01"
ANTHROPIC_BETA = (
    "oauth-2025-04-20,"
    "claude-code-20250219,"
    "interleaved-thinking-2025-05-14,"
    "fine-grained-tool-streaming-2025-05-14"
)
REQUEST_TIMEOUT = 300.0

# Token storage
TOKEN_FILE = Path.home() / ".claude-max-proxy" / "tokens.json"

# Default model
DEFAULT_MODEL = "claude-sonnet-5"

# Available models (Claude 5 + older)
MODELS = {
    # Claude 5 (1M context)
    "claude-sonnet-5": {"context": 1_000_000, "max_output": 64_000},
    "claude-opus-5": {"context": 1_000_000, "max_output": 64_000},
    # Claude 4.6 (1M context)
    "claude-sonnet-4-6": {"context": 1_000_000, "max_output": 64_000},
    "claude-opus-4-6": {"context": 1_000_000, "max_output": 32_000},
    # Claude 4.5
    "claude-sonnet-4-5-20250929": {"context": 200_000, "max_output": 64_000},
    "claude-opus-4-5-20251101": {"context": 200_000, "max_output": 32_000},
    "claude-haiku-4-5-20251001": {"context": 200_000, "max_output": 8_192},
    # Claude 4.0/4.1
    "claude-sonnet-4-20250514": {"context": 200_000, "max_output": 64_000},
    "claude-opus-4-20250514": {"context": 200_000, "max_output": 32_000},
    "claude-opus-4-1-20250805": {"context": 200_000, "max_output": 32_000},
}
