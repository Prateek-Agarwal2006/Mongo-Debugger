# Google ADK (google-adk) — Vertex AI Backend Research

**Date:** 2026-07-21  
**Sources consulted:** Official ADK docs (adk.dev), GitHub google/adk-python, PyPI, google-genai SDK docs, Google Cloud docs, env.dev

---

## 1. Does ADK Support a Vertex AI Backend?

**Yes.** ADK supports two primary backends for Gemini models:

| Backend | Auth method | When to use |
|---|---|---|
| Google AI Studio (Gemini Developer API) | `GEMINI_API_KEY` / `GOOGLE_API_KEY` | Local prototyping, personal projects |
| Vertex AI / Gemini Enterprise Agent Platform | Application Default Credentials (ADC) + project + location | Production, enterprise, GCP-hosted workloads |

The toggle is controlled by the `GOOGLE_GENAI_USE_VERTEXAI` environment variable (original name) or the newer alias `GOOGLE_GENAI_USE_ENTERPRISE` introduced when Google rebranded Vertex AI → Gemini Enterprise Agent Platform in 2026.

Sources:
- [irbox ADK models mirror](https://irbox.github.io/adk-docs/agents/models/) — shows both `GOOGLE_GENAI_USE_VERTEXAI=FALSE` (AI Studio) and `GOOGLE_GENAI_USE_VERTEXAI=TRUE` (Vertex AI) setup blocks
- [DeepWiki ADK model config](https://deepwiki.com/google/adk-docs/3.5-agent-models-and-configuration) — "Toggle with `GOOGLE_GENAI_USE_VERTEXAI` environment variable"
- [env.dev Gemini env vars guide](https://env.dev/guides/gemini-api-env-variables) — detailed comparison of both flags

---

## 2. Environment Variables for Vertex AI

### Required variables

```bash
GOOGLE_GENAI_USE_VERTEXAI=TRUE       # switches ADK off API keys and onto ADC
GOOGLE_CLOUD_PROJECT=your-project-id  # GCP project ID
GOOGLE_CLOUD_LOCATION=us-central1    # Vertex AI region
```

### Optional — service account key file (non-GCP environments)

```bash
GOOGLE_APPLICATION_CREDENTIALS=/path/to/sa-key.json
```

If `GOOGLE_APPLICATION_CREDENTIALS` is **not** set, ADK falls back to [Application Default Credentials](https://cloud.google.com/docs/authentication/application-default-credentials): it checks `gcloud auth application-default login`, the metadata server (on GCE/Cloud Run/GKE), and Workload Identity Federation in that order.

### Complete `.env` example (service account key, e.g. Docker outside GCP)

```bash
GOOGLE_GENAI_USE_VERTEXAI=True
GOOGLE_APPLICATION_CREDENTIALS=sa_creds.json
GOOGLE_CLOUD_PROJECT=my-gcp-project
GOOGLE_CLOUD_LOCATION=us-central1
```

### For AI Studio (no Vertex)

```bash
GOOGLE_API_KEY=YOUR_KEY_HERE
GOOGLE_GENAI_USE_VERTEXAI=FALSE      # or simply omit it — FALSE is the default
```

Sources:
- [irbox ADK models mirror](https://irbox.github.io/adk-docs/agents/models/) — exact env-var blocks for both backends
- [GitHub discussion #396 — service account auth without gcloud](https://github.com/google/adk-python/discussions/396) — maintainer confirmed the `.env` block above works; `GOOGLE_APPLICATION_CREDENTIALS` pointing at a service account JSON is the supported path for containerised environments
- [GKE tutorial — ADK on Vertex AI](https://docs.cloud.google.com/kubernetes-engine/docs/tutorials/agentic-adk-vertex) — uses `GOOGLE_GENAI_USE_VERTEXAI="1"` (equivalent to `TRUE`) plus `GOOGLE_CLOUD_PROJECT_ID` and `GOOGLE_CLOUD_LOCATION` in the deployment manifest; uses Workload Identity Federation instead of a key file on GKE
- [env.dev Gemini env vars guide](https://env.dev/guides/gemini-api-env-variables) — conflict rule: setting both `GOOGLE_GENAI_USE_ENTERPRISE` and `GOOGLE_GENAI_USE_VERTEXAI` to conflicting values raises a `ValueError`

### Note on `GOOGLE_GENAI_USE_ENTERPRISE` (2026 rebrand)

Google renamed the "Vertex AI API" to the **Gemini Enterprise Agent Platform** in 2026. The newer env var is `GOOGLE_GENAI_USE_ENTERPRISE=True`; the older `GOOGLE_GENAI_USE_VERTEXAI=True` remains supported. The two flags are **mutually exclusive** — setting both to conflicting values raises a `ValueError`. Use `GOOGLE_GENAI_USE_VERTEXAI` for now unless you are targeting the new Enterprise Agent Platform product specifically.

Source: [env.dev guide](https://env.dev/guides/gemini-api-env-variables), [DeepWiki ADK config](https://deepwiki.com/google/adk-docs/3.5-agent-models-and-configuration)

---

## 3. Model String Format: Vertex vs AI Studio

**The model string is the same regardless of backend.**

Both AI Studio and Vertex AI use short model identifiers like:

```
"gemini-2.5-flash"
"gemini-2.0-flash"
"gemini-2.5-pro"
"gemini-flash-latest"
```

The underlying `google-genai` SDK routes the request to the correct endpoint based on the `GOOGLE_GENAI_USE_VERTEXAI` / `GOOGLE_GENAI_USE_ENTERPRISE` flag, not on the model string.

Example from the `google-genai` SDK docs showing identical model strings on both backends:

```python
# AI Studio
client = genai.Client(api_key='your-google-ai-api-key')
response = client.models.generate_content(model='gemini-2.0-flash-exp', contents='Why is sky blue?')

# Vertex AI — same model string, different client config
client = genai.Client(vertexai=True, project='your-project-id', location='us-central1')
response = client.models.generate_content(model='gemini-2.0-flash-exp', contents='Why is sky blue?')
```

Source: [Mete Atamel blog — Gen AI SDK unification (Dec 2024)](https://atamel.dev/posts/2024/12-17_vertexai_googleai_united_with_new_genai_sdk/)

### Exception — Vertex AI endpoint resource strings

For models deployed to **Vertex AI Endpoint** (Model Garden, fine-tuned endpoints, Anthropic Claude on Agent Platform), the model string is a full resource path:

```
projects/PROJECT_ID/locations/LOCATION/endpoints/ENDPOINT_ID
```

This is only for custom/non-Gemini endpoints, not for standard Gemini models.

Source: [irbox ADK models mirror](https://irbox.github.io/adk-docs/agents/models/) — "Deploy custom or third-party models to Vertex AI endpoints using full resource strings"

### Model version caveats

- `"gemini-flash-latest"` aliases **may fail** on regional (non-global) Vertex AI endpoints. Use explicit version strings (e.g. `"gemini-2.0-flash-001"`) for regional deployments.
- As of June 1, 2026, `gemini-2.0-flash-001` and `gemini-2.0-flash-lite-001` are discontinued. Use `gemini-2.5-flash` or `gemini-2.5-flash-lite`.

Source: [adk.dev Gemini models page](https://adk.dev/agents/models/google-gemini/) — "gemini-flash-latest may fail when accessing regional endpoints"

---

## 4. Limitations and Caveats

### 4a. Interactions API — NOT fully supported on Vertex AI (as of July 2026)

The ADK Interactions API (Python v1.21.0+, which enables conversational turn management) was **not available on Vertex AI** as of December 2025 per an ADK team member. As of July 2026, partial availability exists but users report failures:

> "When using Vertex AI with service accounts, they receive errors like 'Unsupported model interaction: gemini-3.5-flash', whereas the same code works with API keys."

**Workaround:** Use the standard `runner.run_async()` / `runner.run()` path (not the Interactions API) when authenticating with Vertex AI service accounts. Or use an API key instead, though that is not viable in enterprise IAM-controlled environments.

Source: [GitHub discussion #3914](https://github.com/google/adk-python/discussions/3914) — ADK team member Patrick Loeber confirmed "Interactions API is currently not available in Vertex AI" (Dec 2025); later reports of partial availability but service-account failures (July 2026)

### 4b. ADC wiring bug in ADK 0.5.0 (historical, likely fixed)

ADK 0.5.0 had a bug where `GOOGLE_GENAI_USE_VERTEXAI=TRUE` was set but the `Gemini` class failed to pass ADC context to the underlying generativeai library, raising:

> `ValueError: Project and location or API key must be set when using the Vertex AI API.`

This was an internal wiring bug in `google.adk.models.google_llm.Gemini`, not a configuration error. As of 2026 (ADK is at version 1.x), this is expected to be resolved, but verify by running a simple smoke test after upgrade.

Source: [GitHub issue #718](https://github.com/google/adk-python/issues/718)

### 4c. Regional endpoint limitations

- The `"gemini-flash-latest"` alias can fail on regional endpoints — use explicit version strings.
- `GOOGLE_CLOUD_LOCATION` should be set explicitly; if omitted it may default to `us-central1` or whatever `gcloud` config specifies, which can cause unexpected routing.

Source: [adk.dev Gemini models page](https://adk.dev/agents/models/google-gemini/), [GitHub discussion #3043](https://github.com/google/adk-python/discussions/3043)

### 4d. Voice / Video streaming (Live API)

The Live API (streaming voice/video) uses different model IDs depending on backend:
- **AI Studio:** see [Gemini Live API docs](https://ai.google.dev/gemini-api/docs/models#live-api)
- **Agent Platform / Vertex AI:** see [Agent Platform Live API docs](https://cloud.google.com/vertex-ai/generative-ai/docs/live-api)

The supported model set for Live API may differ between backends. Check the respective docs for the current list.

Source: [adk.dev Gemini models page](https://adk.dev/agents/models/google-gemini/)

### 4e. `cannot` mix custom function tools with built-in tools via Interactions API

When using the Interactions API, you cannot mix custom function tools with built-in tools like Google Search. Set `bypass_multi_tools_limit=True` to convert built-in tools to function-calling tools as a workaround.

Source: [adk.dev Gemini models page](https://adk.dev/agents/models/google-gemini/)

---

## 5. Working Code Example — ADK Agent Configured for Vertex AI

### Option A: via environment variables (recommended for most deployments)

Set your `.env` file (or shell environment):

```bash
GOOGLE_GENAI_USE_VERTEXAI=True
GOOGLE_CLOUD_PROJECT=my-gcp-project
GOOGLE_CLOUD_LOCATION=us-central1
# For non-GCP environments (Docker, CI, etc.):
GOOGLE_APPLICATION_CREDENTIALS=/secrets/sa-creds.json
```

Agent code (`agent.py`) — no Vertex-specific changes needed:

```python
from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService

# Model string is identical for both AI Studio and Vertex AI backends.
# ADK reads GOOGLE_GENAI_USE_VERTEXAI from the environment automatically.
root_agent = LlmAgent(
    name="my_agent",
    model="gemini-2.5-flash",           # same string whether using Vertex or AI Studio
    instruction="You are a helpful assistant.",
    tools=[],
)

# Run the agent
session_service = InMemorySessionService()
runner = Runner(agent=root_agent, app_name="my_app", session_service=session_service)

import asyncio

async def main():
    session = await session_service.create_session(app_name="my_app", user_id="user1")
    from google.adk.types import Content, Part
    result = await runner.run_async(
        user_id="user1",
        session_id=session.id,
        new_message=Content(parts=[Part(text="Hello!")]),
    )
    for event in result:
        if event.is_final_response():
            print(event.content.parts[0].text)

asyncio.run(main())
```

### Option B: explicit client constructor (bypasses env vars, good for testing)

Using the underlying `google-genai` SDK directly (ADK also accepts a pre-configured client via `google.adk.models.Gemini` — see [issue #2560](https://github.com/google/adk-python/issues/2560) for the feature request, which may not yet be GA):

```python
from google import genai

# Vertex AI client — no API key needed
client = genai.Client(
    vertexai=True,
    project="my-gcp-project",
    location="us-central1",
)

response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents="What is 2+2?",
)
print(response.text)
```

Source: [Mete Atamel blog](https://atamel.dev/posts/2024/12-17_vertexai_googleai_united_with_new_genai_sdk/), [irbox ADK models mirror](https://irbox.github.io/adk-docs/agents/models/)

### Option C: GKE / Workload Identity (no key file in container)

In the Kubernetes deployment manifest, set:

```yaml
env:
  - name: GOOGLE_GENAI_USE_VERTEXAI
    value: "1"
  - name: GOOGLE_CLOUD_PROJECT_ID
    value: "YOUR_PROJECT_ID"
  - name: GOOGLE_CLOUD_LOCATION
    value: "us-central1"
```

And configure Workload Identity Federation so the pod's Kubernetes Service Account is linked to a GCP IAM service account. No `GOOGLE_APPLICATION_CREDENTIALS` key file needed.

Source: [GKE + ADK + Vertex AI tutorial](https://docs.cloud.google.com/kubernetes-engine/docs/tutorials/agentic-adk-vertex)

---

## Summary Table

| Question | Answer |
|---|---|
| Vertex AI backend supported? | Yes, via `GOOGLE_GENAI_USE_VERTEXAI=True` |
| Required env vars | `GOOGLE_GENAI_USE_VERTEXAI`, `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION` |
| Optional env var | `GOOGLE_APPLICATION_CREDENTIALS` (for key-file auth outside GCP) |
| Model string changes? | No — `"gemini-2.5-flash"` works on both backends |
| Interactions API on Vertex? | Partially supported as of July 2026; service-account auth has known failures |
| Live API streaming differences? | Yes — supported model set differs; check backend-specific docs |
| `"gemini-flash-latest"` on regional endpoints? | May fail — use explicit version strings |

---

## All Sources

- [adk.dev — Gemini models page](https://adk.dev/agents/models/google-gemini/)
- [adk.dev — Agent Platform hosted models](https://adk.dev/agents/models/agent-platform/)
- [adk.dev — Models overview](https://adk.dev/agents/models/)
- [irbox ADK docs mirror — Models](https://irbox.github.io/adk-docs/agents/models/) (detailed env-var blocks)
- [DeepWiki — ADK model config](https://deepwiki.com/google/adk-docs/3.5-agent-models-and-configuration)
- [Google Gen AI SDK docs](https://googleapis.github.io/python-genai/)
- [env.dev — Gemini API env variables](https://env.dev/guides/gemini-api-env-variables)
- [GitHub discussion #396 — service account without gcloud](https://github.com/google/adk-python/discussions/396)
- [GitHub discussion #3914 — Interactions API + Vertex](https://github.com/google/adk-python/discussions/3914)
- [GitHub discussion #3043 — region/location defaults](https://github.com/google/adk-python/discussions/3043)
- [GitHub issue #718 — ADK 0.5.0 ADC bug](https://github.com/google/adk-python/issues/718)
- [GitHub issue #2560 — pre-configured genai.Client request](https://github.com/google/adk-python/issues/2560)
- [GKE tutorial — ADK on Vertex AI](https://docs.cloud.google.com/kubernetes-engine/docs/tutorials/agentic-adk-vertex)
- [Mete Atamel blog — Gen AI SDK unification](https://atamel.dev/posts/2024/12-17_vertexai_googleai_united_with_new_genai_sdk/)
- [PyPI — google-adk](https://pypi.org/project/google-adk/)
