# Provider profiles for run workers

From a project overview, choose **Provider settings**. Chat and Embeddings each
have their own provider, API root, optional model override and key. Omit the
model for the evaluator's native default. Every profile is encrypted with the
volume's `credential.key`. Persist the whole volume across restarts.

**Check readiness and discover models** reads the saved profile's model catalog
over verified HTTPS. Configure a private CA in the Studio process trust store
(or `SSL_CERT_FILE`). Discovery never follows redirects and does not run a
generation or embedding trial. A listed model confirms catalog access, not
inference permission or billing capacity. Bedrock uses the worker’s AWS identity
instead of a saved API key and has no Studio catalog probe.

## Python boundary

```python
from studio.providers import worker_environment
from skillevaluator.provider_config import resolve_llm_provider, resolve_embedding_provider

chat_env = worker_environment(workspace, project.id, "chat")
chat = resolve_llm_provider(chat_env)
embedding_env = worker_environment(workspace, project.id, "embeddings")
embedding = resolve_embedding_provider(embedding_env)
```

Each call reads a fresh snapshot and returns a fresh mapping. An absent or
incomplete profile raises `ValueError`; keyless static runs need neither
profile. Resolve only the roles the job requires. For a reproducible queued
run, snapshot inputs at enqueue time; retain secrets only in encrypted
worker-private storage. Only provider, model and base URL belong in public
configuration or reports.

Pass the separate resolved configs to role-specific clients. For a CLI that
reads process environment, launch a dedicated child with `env={**runtime_env,
**chat_env}` (or `embedding_env`). Build `runtime_env` from an allowlist of
non-provider settings; include operator AWS identity settings only for
Bedrock. Do not inherit ambient provider keys, endpoints, proxies or extra
headers, merge the two role maps, or update `os.environ`. Some native
providers use the same variable name for both keys. A combined workflow must
route roles separately rather than choosing one key for both.

Treat resolved objects, environment maps, and raw provider responses as
secrets. Do not print them or pass keys in argv. Configure inference clients
to reject redirects as the catalog probe does.
