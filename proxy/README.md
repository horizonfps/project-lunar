# Claude Max Proxy

Routes Anthropic API requests through your Claude Pro/Max subscription instead of using API credits. Supports **all models** including Sonnet 4.6 and Opus 4.6.

## CLIProxyAPI (recommended)

Uses [CLIProxyAPI](https://github.com/router-for-me/CLIProxyAPI) — a Go binary that wraps the Claude Code OAuth flow into an Anthropic-compatible API server. Gives access to **all subscription models** (Sonnet 4.6, Opus 4.6, Sonnet 4.5, Opus 4.5, Haiku 4.5, etc.).

### Setup

```bash
cd proxy/cliproxyapi

# First time: authenticate (opens browser)
./cli-proxy-api.exe -claude-login -config config.yaml

# Start the proxy server (port 8317)
./cli-proxy-api.exe -config config.yaml
```

### .env config

```
ANTHROPIC_PROXY_URL=http://127.0.0.1:8317
ANTHROPIC_PROXY_KEY=lunar-proxy-key
```

### Verify

```bash
# List models
curl -s http://127.0.0.1:8317/v1/models -H "Authorization: Bearer lunar-proxy-key" | python -m json.tool

# Test Sonnet 4.6
curl -s -X POST http://127.0.0.1:8317/v1/messages \
  -H "Authorization: Bearer lunar-proxy-key" \
  -H "Content-Type: application/json" \
  -H "anthropic-version: 2023-06-01" \
  -d '{"model":"claude-sonnet-4-6","max_tokens":50,"messages":[{"role":"user","content":"Say hi"}]}'
```

### Notes

- The backend's `LLMRouter` falls back to non-streaming when using the proxy (CLIProxyAPI streaming adds extra fields that confuse litellm's SSE parser). Text arrives as a single chunk instead of token-by-token.
- Auth credentials are saved in `~/.cli-proxy-api/`. Token auto-refreshes every 15 minutes.
- The API key (`lunar-proxy-key`) is configured in `config.yaml` and matched in `.env` via `ANTHROPIC_PROXY_KEY`.

---

## Legacy OAuth Proxy (Haiku only)

The original Python-based OAuth proxy in `proxy/`. Only supports Haiku due to Anthropic's OAuth scope restrictions.

### Setup

```bash
pip install -r requirements.txt
python run.py auth    # authenticate
python run.py serve   # start on port 8082
```

### .env config

```
ANTHROPIC_PROXY_URL=http://127.0.0.1:8082
ANTHROPIC_PROXY_KEY=proxy
```

### Limitations

- OAuth `user:inference` scope only allows **Haiku** models. Sonnet/Opus return `invalid_request_error`.
- Token expires ~8 hours; auto-refreshes via refresh token.
