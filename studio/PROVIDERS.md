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

## Project readiness

Use **Project readiness** on the same page to run the installed evaluator in a
private temporary directory. Blank fields leave CLI defaults intact. Results
show native check details, pass/warn/fail and the evaluator exit code. Select
**Show redacted JSON** for the native report structure. Checks do not change the
project or start a trial.

| Action | What it checks |
| --- | --- |
| Check tier readiness (`doctor`) | Tier 1 probes the installed scanners for the selected checks. Tier 2 resolves each saved provider independently. Tier 3 checks runtime prerequisites. **All** returns the tiers in order. The default is Tier 3. |
| Quick health check (`health-check`) | Same tier scopes, scanner and agent/environment controls, without inference or agent-model overrides. |
| Inspect the live runtime (`tier3 doctor`) | Native Tier 3 only; leave tier scope unset. Select agents, backend and installed environment. An empty agent selection follows the provider. Select **Allow provider probes** to check the resolved agent models against their catalogs. |
| Discover chat models (`models`) | Authenticated, filtered native catalog with the configured model first; limit 1–100 (default 10). No inference. For embedding catalog access use the separate Embeddings profile button. |

**Allow provider probes** is off on every new form. With Tier 2 selected it
authorizes one live embedding and one chat probe, potentially billable. A
catalog listing alone does not verify inference permission. Missing extras,
credentials, scanner executables and backend prerequisites produce native
failures; a missing NeMo Gym CLI is not a successful check.

The worker needs the installed evaluator, Tier 2 SDKs for inference, and
Tier 3 extras and runtime tools for full runtime checks. Provide a trusted
CA for private HTTPS endpoints. Docker needs a reachable daemon; Kata also
needs a registered Kata runtime. Environment choices come from the installed
engine; Studio supplies typed constructor controls for `kata_runtime` and one
`kata_dns` address only. No raw constructor JSON, host paths or
operator cloud credentials can be entered in this form. Cloud backends,
Bedrock identity and a compatible NeMo Gym installation have not been
qualified here.

The per-probe timeout accepts positive values up to 60 seconds for scanners
and explicit Tier 2 inference. The entire worker has a separate 90-second
deadline. Studio passes saved role-specific configuration instead of ambient
provider keys. The [30 bindings](bindings/readiness.json) cite Chromium and
native engine evidence using local HTTPS fixtures, not a hosted provider.

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

## Private HTTPS inference in a Harbor trial

Set `SSL_CERT_FILE` in the **Studio worker** environment, e.g.
`SSL_CERT_FILE=/etc/studio/pki/model-roots.pem`. Relative paths resolve from
Studio's launch directory. Supply a regular PEM file of public X.509
certificates only (up to 2 MiB); private keys, mixed PEM objects and malformed
bundles are rejected. The public certificates become part of each trial image
and may be retained with Harbor jobs. No host trust directory is mounted into
trials. The image combines these anchors with its system roots for Python and
sets `NODE_EXTRA_CA_CERTS` for OpenCode. Requeue trials after CA rotation.

Use an HTTPS API root whose **hostname and port are reachable from both the
worker and the Docker network**, with that name in the server certificate.
`localhost` in a trial points to the trial itself. Save chat and embedding
settings independently. In **Live Tier 3 → Trial settings and budgets** the
saved chat model is the standard judge; the shared agent override and the more
specific per-agent overrides select the trial models. For example, select
OpenCode and enter `openai/private-agent` while saving `private-judge` for
chat. The endpoint must serve both model IDs. Embedding credentials are not
needed by the trial.

To exercise this path locally, run `STUDIO_TEST_LIVE_RUNTIME=1 python -m
pytest tests/studio/test_private_trial.py` in the installed Studio + Harbor
environment, with Docker Compose and access to the local Docker bridge. The
fixture serves inference locally; normal container and agent installation
may download dependencies.
