# LLM providers

Three API styles are built in, plus a preset for Grok. Each works with the vendor's own API and with any server that copies that API. To use another server, set its base URL with `--api-base`, `"API_BASE"` in settings, or the env var below.

| `PROVIDER`  | API               | Default model       | API key env var     | Base URL env var     | Default base URL                            |
| ----------- | ----------------- | ------------------- | ------------------- | -------------------- | ------------------------------------------- |
| `openai`    | Chat Completions  | `gpt-6-luna`        | `OPENAI_API_KEY`    | `OPENAI_BASE_URL`    | `https://api.openai.com/v1`                 |
| `anthropic` | Messages          | `claude-sonnet-5-5` | `ANTHROPIC_API_KEY` | `ANTHROPIC_BASE_URL` | `https://api.anthropic.com`                 |
| `gemini`    | `generateContent` | `gemini-3.8-flash`  | `GEMINI_API_KEY`    | `GEMINI_BASE_URL`    | `https://generativelanguage.googleapis.com` |
| `grok`      | Chat Completions  | `grok-4.7`          | `XAI_API_KEY`       | `XAI_BASE_URL`       | `https://api.x.ai/v1`                       |

As each vendor's tooling does, an `openai` or `grok` base URL includes the `/v1` and the others don't.

The model is, in order, `--model`, `"MODEL"` in settings, the `LLM_LOCALIZE_MODEL` environment variable, and then the provider's default from the table. The defaults are the current models when a version is released; when a provider retires one, an older version stops with an error naming the model, and setting `LLM_LOCALIZE_MODEL` once (or upgrading) gets it going again.

The API key is read, in order, from `--api-key`, `"API_KEY"` in settings, the `LLM_LOCALIZE_API_KEY` environment variable (used for every provider), and then the provider's own variable from the table. The provider's own variable is only used for the provider's own API: with a different `--api-base`, pass the key explicitly or set `LLM_LOCALIZE_API_KEY`, so an OpenAI key is never sent to some other server. On a shared machine, prefer the environment variables to `--api-key`, which other users can see in the process list.

The API key is required for the vendor's own API, and optional anywhere else, so local servers work without one:

```bash
# Ollama, vLLM, LM Studio, or any OpenAI-compatible server
llm-localize messages.po --api-base http://localhost:11434/v1 --model qwen3

# A hosted OpenAI-compatible gateway
llm-localize messages.po --api-base https://openrouter.ai/api/v1 --model <model-id> --api-key ...

# Claude, through a company proxy
llm-localize messages.po --provider anthropic --api-base https://llm-proxy.example.com
```

Notes by provider:

- **`openai`** asks for a `json_schema` response. For a server that doesn't support it, set `MODEL_PARAMS = {"response_format": {"type": "json_object"}}`, or `{"response_format": None}` to send none. Requests use `temperature: 0.2`.
- **`anthropic`** sends API version `2026-10-21`, which rejects sampling parameters, so it sends no `temperature`. On Anthropic's own API it also turns on server-side refusal fallbacks (`fallbacks: "default"`), so a request a safety classifier declines is retried on another model. They're a beta feature: if the API stops accepting it, requests go on without it, with a warning. A request that is still declined fails that batch, and the batch is retried on the next run.
- **`gemini`** asks for `application/json` and leaves temperature at the model's default, which Google recommends for Gemini 3 models.
- **`grok`** sends the same requests as `openai`, which xAI's API accepts.

`MODEL_PARAMS` are merged into the request body, with dict values merged one level deep. Use them for anything provider-specific, e.g. `{"output_config": {"effort": "low"}}` for Claude, or `{"generationConfig": {"temperature": 0.2}}` for Gemini.

Rate limits (429), overload (500/502/503/504/529), timeouts and connection failures are retried up to 5 times, waiting as long as the server's `Retry-After` asks (up to 5 minutes), or otherwise 1–2, 2–4, 4–8, 8–16 and 16–32 seconds. A reply that reaches the model's output token limit fails its batch with a message to use a smaller batch size. Authentication, billing, permission and not-found errors (401/402/403/404), such as a wrong API key or model name, stop the run at once, since every request would fail the same way.
