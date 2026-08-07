# CLIProxyAPI Subscription Proxy

Routes Anthropic and OpenAI-compatible requests through authenticated subscriptions. Project Lunar uses it for Claude models and `gpt-5.6-sol`.

## CLIProxyAPI (recommended)

Uses [CLIProxyAPI](https://github.com/router-for-me/CLIProxyAPI), a Go binary that exposes Anthropic and OpenAI-compatible local APIs backed by OAuth credentials.

### Setup

```bash
cd proxy/cliproxyapi

# Authenticate providers that are not already configured
./cli-proxy-api.exe -claude-login -config config.yaml
./cli-proxy-api.exe -codex-login -config config.yaml

# Start the proxy server (port 8318)
./cli-proxy-api.exe -config config.yaml
```

### .env config

```
ANTHROPIC_PROXY_URL=http://127.0.0.1:8318
ANTHROPIC_PROXY_KEY=lunar-proxy-key
OPENAI_PROXY_URL=http://127.0.0.1:8318/v1
OPENAI_PROXY_KEY=lunar-proxy-key
```

### Verify

```bash
# List models
curl -s http://127.0.0.1:8318/v1/models -H "Authorization: Bearer lunar-proxy-key" | python -m json.tool

# Test Sonnet 4.6
curl -s -X POST http://127.0.0.1:8318/v1/messages \
  -H "Authorization: Bearer lunar-proxy-key" \
  -H "Content-Type: application/json" \
  -H "anthropic-version: 2023-06-01" \
  -d '{"model":"claude-sonnet-4-6","max_tokens":50,"messages":[{"role":"user","content":"Say hi"}]}'

# Test GPT-5.6 Sol
curl -s -X POST http://127.0.0.1:8318/v1/chat/completions \
  -H "Authorization: Bearer lunar-proxy-key" \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-5.6-sol","max_tokens":50,"messages":[{"role":"user","content":"Say hi"}]}'
```

### Notes

- The backend's `LLMRouter` falls back to non-streaming when using the proxy (CLIProxyAPI streaming adds extra fields that confuse litellm's SSE parser). Text arrives as a single chunk instead of token-by-token.
- Auth credentials are saved in `~/.cli-proxy-api/`. Token auto-refreshes every 15 minutes.
- The API key (`lunar-proxy-key`) is configured in `config.yaml` and matched in `.env` through the provider-specific proxy key variables.
- An existing CLIProxyAPI instance may use a different local port and key through the untracked `.env`.

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
