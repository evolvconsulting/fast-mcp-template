# FastMCP — Current Developer Reference

**Target: `fastmcp==4.0.3` on Python 3.12.** Last revised 2026-09-08, when the pin moved from the beta `4.0.0b4` to the GA line. Only the pin, the release table and the dependency facts were re-derived on 4.0.3; every `[FROM SOURCE]` listing below was enumerated on 4.0.0b4 and has NOT been re-enumerated. Treat signatures as indicative until they are.

Research method: PyPI JSON API, the official docs site `gofastmcp.com`, `modelcontextprotocol.io`,
and direct inspection of installed source trees. Claims read out of a source tree rather than the
docs are tagged `[FROM SOURCE]`. Claims marked **[SPIKE]** were executed; a
**[FASTMCP-SPIKE-4.md §n]** tag names the section of
[`FASTMCP-SPIKE-4.md`](FASTMCP-SPIKE-4.md) holding the evidence. The section number
belongs to THAT document, never to this one - both files number their sections from
1, so a bare `§7` here would read as this document's §7 and point at the wrong text.

> **Changelog.** This document originally recommended pinning `fastmcp>=3.4.7,<4.0.0` and staying
> off the 4.0 beta. Phil overruled that on 2026-08-27: we are deliberate early adopters of
> 4.0.0b4 and the sessionless 2026-07-28 spec. The prose below has been rewritten to the new
> target rather than annotated, so nothing here describes 3.4.7 as our version. Sections that
> were never re-verified on 4.0 are marked as such inline.

---

## Bottom line for our build

| Decision | Recommendation |
|---|---|
| **Version to pin** | `fastmcp==4.0.3` as the only direct fastmcp dependency. While 4.x was a prerelease (until 2026-08-31) the pin also had to name `fastmcp-slim==4.0.0b4` and set `[tool.uv] prerelease = "explicit"`, because uv will not pull a transitive prerelease nobody named and without it the resolver either failed or dragged in a *beta pydantic*. **[FASTMCP-SPIKE-4.md §1.3]** A GA pin resolves `fastmcp-slim` on its own (measured 2026-09-08: `uv lock` moved both to 4.0.3 with nothing else named). Watch `mcp`, which resolves to 2.1.1 beneath 4.0.3: the one 4.0 defect we found was caused by a dependency major-bump underneath unchanged code. |
| **Python floor** | **3.12** (per the standards). Verified working on 3.11.15 and 3.12.3; behaviour identical. **[FASTMCP-SPIKE-4.md §10.1]** |
| **MCP spec revision we get** | **`2026-07-28`** (sessionless) by default, and `2025-11-25` for handshake-era clients — both served simultaneously from one server on one port. Proven, not quoted. **[FASTMCP-SPIKE-4.md §3.3]** |
| **Transport** | **stdio by default**, Streamable HTTP opt-in via config. `mcp.run(transport="http", host=..., port=..., path="/mcp")`; `/mcp` is also the default path. `sse` is deprecated. A public repo gets both local and hosted users, so hardcoding HTTP locks out every local client. **[FASTMCP-SPIKE-4.md §7]** |
| **Auth** | `StaticTokenVerifier` from `fastmcp.server.auth.providers.jwt`, token dict loaded from the environment. Never hand-roll a `TokenVerifier` subclass. Per-tool authorization via `@mcp.tool(auth=require_scopes(...))`. **[FASTMCP-SPIKE-4.md §4]** |
| **Errors** | `raise ToolError(...)` for anything actionable; let unexpected exceptions raise and set `mask_error_details=True`. **[FASTMCP-SPIKE-4.md §5]** |
| **Required config** | pydantic-settings with non-defaulted fields. `fastmcp.json` **cannot** express a required env var and fails *silently*. **[FASTMCP-SPIKE-4.md §10]** |
| **Mandatory workaround** | An **explicit** SIGTERM handler that raises `KeyboardInterrupt`, plus `os._exit(0)` after `run()` returns — or lifespan teardown never runs on container stop, and on stdio the process survives SIGTERM entirely. Do **not** use `signal.getsignal(SIGINT)`: it can install *ignore SIGTERM*. **[FASTMCP-SPIKE-4.md §19.5]** |

### The httpx → httpx2 decision (open)

4.0 replaces `httpx` with **`httpx2`**, which reaches the public API (`Client.__init__` is typed
`auth: httpx2.Auth`). `httpx` is not installed at all. The two **do** coexist as separate modules,
so our Jobvite client may use either — but `except httpx.HTTPError` will never catch a
FastMCP-raised exception. Keep every `except httpx.*` in one module. **[FASTMCP-SPIKE-4.md §1.2]**

### Top 5 things `fast-mcp-jira` does that we must not copy

1. **`mcp-server.json` is not a FastMCP artifact.** Zero hits across the installed package `[FROM SOURCE]`. The real manifest is **`fastmcp.json`** (`source` required, plus `environment`, `deployment`). `fast-mcp-jira`'s `env_vars` array with `display_name`/`sensitive`/`validation` is a half-remembered **`server.json`** (the MCP Registry artifact, whose keys are `environmentVariables`/`isRequired`/`isSecret`) under the wrong filename with the wrong casing — which is exactly why nothing reads it. See §12(b).
2. **Hand-rolled `ApiKeyVerifier(TokenVerifier)`** (`auth.py`) — reimplements `StaticTokenVerifier` plus a bespoke `AuthRateLimiter`. ~150 lines to delete. Note the framework's own `RateLimitingMiddleware` is **not per-client by default** and needs an explicit `get_client_id` **[FASTMCP-SPIKE-4.md §13.1]**.
3. **A stale version floor.** `fastmcp>=3.1.0` (2026-03-03) hides `MultiAuth`, `run_in_thread`, `AuthCheck`/`require_scopes`, tool `timeout=`, and the whole `providers/` auth directory.
4. **Tools return `build_response(False, error=...)` dicts on failure**, so the client sees `isError: false` on every upstream 4xx. Raise `ToolError` instead.
5. **Hardcoded HTTP transport with no stdio path** (`__main__.py`), plus custom logging/caching infrastructure that framework middleware now covers.

**NOT outdated, verified twice:** `from fastmcp.server.lifespan import lifespan` used as a decorator
**survives into 4.0.0b4**, and `|` composition works. Do not "fix" that import. **[FASTMCP-SPIKE-4.md §2]**

---

## 1. Versions and the MCP spec revision

Source: `https://pypi.org/pypi/fastmcp/json`.

| Version | Uploaded (ISO 8601) |
|---|---|
| 3.0.0 | 2026-02-18 |
| 3.1.0 | 2026-03-03 |
| 3.2.0 | 2026-03-30 |
| 3.3.0 | 2026-05-15 |
| 3.4.0 | 2026-06-03 |
| **3.4.7 (latest stable)** | **2026-08-10T21:17:51Z** |
| 4.0.0b1 | 2026-07-28 |
| 4.0.0b4 | 2026-08-26T22:59:04Z |
| 4.0.0b5 | 2026-08-28 |
| 4.0.0 (GA) | 2026-08-31 |
| 4.0.1, 4.0.2 | 2026-09-02 |
| 4.0.3 (latest as of 2026-09-08) | 2026-09-05 |

- `fastmcp` is a thin metapackage whose only base dependency is the matching `fastmcp-slim` (`fastmcp-slim[client,server]==4.0.3` at 4.0.3). **Naming both was required only while 4.x was a prerelease** - see the Bottom line. Extras: `anthropic`, `apps`, `azure`, `code-mode`, `gemini`, `openai`, `tasks`.
- `fastmcp-slim` 4.0.0b4 depends on `mcp>=2.0.0,<3.0.0` and `httpx2>=2.5.0` — a **major** SDK jump vs the 3.x line.

### MCP protocol revision

- Installed `mcp` is **1.29.0**. `mcp.types.LATEST_PROTOCOL_VERSION == "2025-11-25"`, `DEFAULT_NEGOTIATED_VERSION == "2025-03-26"` `[FROM SOURCE]`.
- **The docs site does not publish an "implements spec revision X" statement for any FastMCP release.** For 4.0 this no longer matters: the server itself reports its supported versions via `server/discover`, and that was executed **[FASTMCP-SPIKE-4.md §3.1]**.
- Per `https://modelcontextprotocol.io/specification/versioning`: *"The **current** protocol version is [**2026-07-28**]."* That revision replaces the initialize-handshake with per-request version declaration via `io.modelcontextprotocol/protocolVersion` in `_meta` (and the `MCP-Protocol-Version` header over Streamable HTTP), adds a mandatory `server/discover` RPC, and returns `UnsupportedProtocolVersionError` on mismatch.
- Per `https://gofastmcp.com/updates`, FastMCP **4.0.0b1** is where dual-era support lands: *"Dual protocol support: both sessionless `2026-07-28` and older session-based handshake per connection."*

### Version and spec facts

- `fastmcp` 4.0.0 went GA on **2026-08-31** and 4.0.3 followed on 2026-09-05 (PyPI upload dates); the last 3.x release was 3.4.7 on 2026-08-10. `requires_python >=3.10`.
- 4.0 resolves to `mcp` **2.1.1**, `mcp-types` 2.1.1, `starlette` 1.6.0, `httpx2` 2.12.0, and requires `pydantic>=2.12`. **[FASTMCP-SPIKE-4.md §1.1]**
- The current published MCP spec revision is **`2026-07-28`**, per `https://modelcontextprotocol.io/specification/versioning`. 4.0 serves it **and** the older handshake revisions from the same server. **[FASTMCP-SPIKE-4.md §3]**
- `server/discover` reports `supportedVersions: ["2026-07-28"]` **only**, despite demonstrably serving 2025-11-25 clients — do not treat that list as exhaustive. **[FASTMCP-SPIKE-4.md §3.1]**

---

## 2. Server construction — `FastMCP(...)`

Signature `[FROM SOURCE]`, `fastmcp.server.server.FastMCP.__init__`, **v4.0.0b4**:

```
FastMCP(
    name: str | None = None,
    instructions: str | None = None,
    *,
    version: str | int | float | None = None,
    website_url: str | None = None,
    icons: list[mcp_types.Icon] | None = None,
    auth: AuthProvider | None = None,
    middleware: Sequence[Middleware] | None = None,
    providers: Sequence[Provider] | None = None,
    transforms: Sequence[Transform] | None = None,
    lifespan: LifespanCallable | Lifespan | None = None,
    tools: Sequence[Tool | Callable[..., Any]] | None = None,
    on_duplicate: DuplicateBehavior | None = None,
    mask_error_details: bool | None = None,
    dereference_schemas: bool = True,
    strict_input_validation: bool | None = None,
    list_page_size: int | None = None,
    resource_security: ResourceSecurity | None = ResourceSecurity(
        reject_path_traversal=True, reject_absolute_paths=True,
        reject_null_bytes=True, exempt_params=frozenset()),
    request_state_security: RequestStateSecurity | None = None,
    cache_ttl: int | None = None,
    cache_scope: Literal["public", "private"] | None = None,
    tasks: bool | None = None,
    session_state_store: AsyncKeyValue | None = None,
    client_log_level: mcp_types.LoggingLevel | None = None,
    experimental_capabilities: dict[str, dict[str, Any]] | None = None,
    **kwargs: Any,
)
```

Changed from 3.x: **`sampling_handler` and `sampling_handler_behavior` are gone**; `resource_security`,
`request_state_security`, `cache_ttl` and `cache_scope` are new.

Notes:
- `middleware=[...]` can be passed at construction, or added later with `mcp.add_middleware(...)`.
- `mask_error_details` defaults to `False` `[FROM SOURCE]` — turn it **on** for a production HTTP deployment.
- `sampling_handler` is present in 3.x and **removed in 4.0**. Don't use it.

### Global settings

`fastmcp.settings` is a pydantic-settings object with `env_prefix = "FASTMCP_"` `[FROM SOURCE]`. Defaults observed:

```
host = 127.0.0.1
port = 8000
streamable_http_path = "/mcp"
stateless_http = False
json_response = False
mask_error_details = False
log_level = INFO
```

So `FASTMCP_PORT`, `FASTMCP_MASK_ERROR_DETAILS`, etc. work out of the box — one more reason our config layer can be thinner than `fast-mcp-jira`'s.

---

## 3. Tools — `@mcp.tool`

Signature `[FROM SOURCE]`, **v4.0.0b4**:

```
FastMCP.tool(
    name_or_fn: str | AnyFunction | None = None,
    *,
    name: str | None = None,
    version: str | int | None = None,
    title: str | None = None,
    description: str | None = None,
    icons: list[mcp.types.Icon] | None = None,
    tags: set[str] | None = None,
    output_schema: dict[str, Any] | NotSetT | None = ...,
    annotations: ToolAnnotations | dict[str, Any] | None = None,
    meta: dict[str, Any] | None = None,
    app: AppConfig | dict[str, Any] | bool | None = None,
    task: bool | TaskConfig | None = None,
    timeout: float | None = None,
    auth: AuthCheck | list[AuthCheck] | None = None,
    run_in_thread: bool = True,
) -> ...
```

⚠️ **`exclude_args` was removed in 4.0** — inject hidden parameters with `Depends()` instead.

Options worth using: **`timeout`** (per-tool execution limit, returns an MCP error), **`auth`** (per-tool `AuthCheck` / `require_scopes(...)`), **`run_in_thread`** (sync functions), **`version`**, **`title`**, **`meta`**.

### Parameter documentation (from `https://gofastmcp.com/servers/tools`)

Docstrings are parsed — Google, NumPy and Sphinx styles — for per-parameter descriptions:

```python
@mcp.tool
def process_image(image_url: str, resize: bool = False) -> dict:
    """Process an image with optional resizing.

    Args:
        image_url: URL of the image to process.
        resize: Whether to resize the image.
    """
```

`Annotated` + pydantic `Field` for validation *and* documentation:

```python
from typing import Annotated
from pydantic import Field

@mcp.tool
def search_products(
    query: Annotated[str, Field(description="Search term")],
    limit: Annotated[int, Field(10, description="Max results", ge=1, le=100)]
) -> list[dict]:
    """Search the product catalog."""
```

Shorthand `Annotated[str, "description text"]` also works.

### Structured content / output schemas

- Object-like returns (`dict`, pydantic model, dataclass) automatically become structured content.
- Primitive returns need a return annotation, and get wrapped under a `"result"` key:

```python
@mcp.tool
def calculate_sum(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b  # Returns structured: {"result": 8}
```

- Override with `output_schema=`:

```python
@mcp.tool(output_schema={
    "type": "object",
    "properties": {"data": {"type": "string"}}
})
def custom_tool() -> dict:
    return {"data": "value"}
```

### Errors — `ToolError` vs returning dicts

From `https://gofastmcp.com/servers/tools`:

```python
from fastmcp.exceptions import ToolError

@mcp.tool
def divide(a: float, b: float) -> float:
    """Divide a by b."""
    if b == 0:
        raise ToolError("Division by zero not allowed.")
    return a / b
```

Rule as documented: by default raised exceptions are logged and converted to MCP error responses. With `mask_error_details=True` on the `FastMCP` instance, non-`ToolError` exceptions show a generic message; **`ToolError` messages always transmit regardless of masking.**

Full exception hierarchy `[FROM SOURCE]`, `fastmcp/exceptions.py`: `FastMCPError` (base, takes `log_level=`), `ValidationError`, `ResourceError`, `ToolError`, `PromptError`, `AuthorizationError`, plus `ClientError`, `NotFoundError`, `DisabledError`, `InvalidSignature`, `FastMCPDeprecationWarning`.

**Guidance for our build:** raise `ToolError` for anything the caller can act on (bad issue key, 404, permission denied); let unexpected exceptions bubble and rely on `mask_error_details=True`. Drop the `build_response(False, ...)` pattern.

---

## 4. Resources, templates, prompts

`[FROM SOURCE]`, **v4.0.0b4**:

```
FastMCP.resource(
    uri: str, *, name=None, version=None, title=None, description=None,
    icons=None, mime_type=None, tags=None,
    annotations: Annotations | dict | None = None,
    meta=None, app=None, task=None, auth: AuthCheck | list[AuthCheck] | None = None,
)

FastMCP.prompt(
    name_or_fn=None, *, name=None, version=None, title=None, description=None,
    icons=None, tags=None, meta=None, task=None,
    auth: AuthCheck | list[AuthCheck] | None = None,
)
```

Templates are still expressed as URI placeholders on `@mcp.resource("...{param}...")` with matching function parameters — that has not changed shape since 3.x. What *is* new relative to 3.1: `version`, `title`, `icons`, `meta`, `task`, and `auth` on both decorators.

**Absence noted:** I did not find a docs page asserting any breaking change to the resource/prompt decorator *semantics* within the 3.x line. The 4.0 upgrade guide does introduce one (see §10: `..`/absolute-path rejection in templated resources, and the resource-not-found wire code change).

---

## 5. Authentication — the current supported way

`fastmcp.server.auth.__init__.__all__` `[FROM SOURCE]`:

```
AccessToken, AuthCheck, AuthContext, AuthProvider, DebugTokenVerifier,
JWTVerifier, MultiAuth, OAuthProvider, OAuthProxy, OIDCProxy,
RemoteAuthProvider, StaticTokenVerifier, TokenVerifier,
require_scopes, restrict_tag, run_auth_checks
```

Class hierarchy `[FROM SOURCE]`, `fastmcp/server/auth/auth.py`:
`AuthProvider(TokenVerifierProtocol)` → `TokenVerifier(AuthProvider)` → concrete verifiers.
`AuthProvider.__init__(base_url=None, required_scopes=None, resource_base_url=None)`; `TokenVerifier` takes the same three. Both declare `async def verify_token(self, token: str) -> AccessToken | None`.

Ready-made providers under `fastmcp/server/auth/providers/`: `auth0, aws, azure, clerk, debug, descope, discord, github, google, huggingface, in_memory, introspection, jwt, keycloak, oci, propelauth, scalekit, supabase, workos`.

### For bearer / API-key auth — verbatim from `https://gofastmcp.com/servers/auth/token-verification`

**Static tokens (dev / shared-secret API keys):**

```python
from fastmcp.server.auth.providers.jwt import StaticTokenVerifier

verifier = StaticTokenVerifier(
    tokens={
        "dev-alice-token": {
            "client_id": "alice@company.com",
            "scopes": ["read:data", "write:data", "admin:users"]
        },
        "dev-guest-token": {
            "client_id": "guest-user",
            "scopes": ["read:data"]
        }
    },
    required_scopes=["read:data"]
)
```

`StaticTokenVerifier` implements constant-lookup verification, `expires_at` checking, and required-scope subset checking `[FROM SOURCE]`. **Its own docstring carries a warning: "WARNING: Never use this in production - tokens are stored in plain text!"** — meaning: don't hardcode them; loading the token dict from env/secret store at startup is the intended shape.

**Custom predicate without subclassing:**

```python
from fastmcp.server.auth.providers.debug import DebugTokenVerifier

async def validate_token(token: str) -> bool:
    return await redis.exists(f"valid_tokens:{token}")

verifier = DebugTokenVerifier(validate=validate_token)
```

**JWT (production, real IdP):**

```python
from fastmcp import FastMCP
from fastmcp.server.auth.providers.jwt import JWTVerifier

verifier = JWTVerifier(
    jwks_uri="https://auth.yourcompany.com/.well-known/jwks.json",
    issuer="https://auth.yourcompany.com",
    audience="mcp-production-api"
)

mcp = FastMCP(name="Protected API", auth=verifier)
```

Also documented: symmetric HMAC (`public_key="...", algorithm="HS256"`), static PEM public key, and **opaque token introspection**:

```python
from fastmcp.server.auth.providers.introspection import IntrospectionTokenVerifier

verifier = IntrospectionTokenVerifier(
    introspection_url="https://auth.yourcompany.com/oauth/introspect",
    client_id="mcp-resource-server",
    client_secret="your-client-secret",
    required_scopes=["api:read", "api:write"]
)
```

**On custom subclasses:** the docs say you *can* "subclass `TokenVerifier` to implement custom validation logic" but **give no worked example**. Reported as an absence: there is no blessed cookbook for a hand-rolled verifier, which is itself a signal to use `StaticTokenVerifier` / `DebugTokenVerifier` instead.

**Per-tool authorization** is separate and newer: `require_scopes(...)` / `restrict_tag(...)` returning `AuthCheck` objects, passed as `@mcp.tool(auth=...)`. `MultiAuth` (3.3.0) composes several verifiers.

`OAuthProxy` (`fastmcp/server/auth/oauth_proxy/`) and `OIDCProxy` exist for fronting a non-DCR upstream IdP — not needed for a service-to-service Jobvite server.

---

## 6. Transports

From `https://gofastmcp.com/deployment/running-server`, three transports: **STDIO** (default), **HTTP (Streamable)**, **SSE (legacy)**. Verbatim: *"We recommend using HTTP transport instead of SSE for all new projects. SSE remains available only for compatibility with older clients."*

```python
mcp.run()                                              # STDIO (default)
mcp.run(transport="http", host="127.0.0.1", port=8000) # Streamable HTTP
mcp.run(transport="sse",  host="127.0.0.1", port=8000) # legacy, deprecated
```

Endpoint: `http://localhost:8000/mcp`. Default `streamable_http_path = "/mcp"` `[FROM SOURCE]`.

Full kwargs accepted through `mcp.run(transport="http", ...)` `[FROM SOURCE]`, `FastMCP.run_http_async`:

```
show_banner: bool = True,
transport: Literal["http", "streamable-http", "sse"] = "http",
host: str | None = None,
port: int | None = None,
log_level: str | None = None,
path: str | None = None,
uvicorn_config: dict[str, Any] | None = None,
middleware: list[ASGIMiddleware] | None = None,
json_response: bool | None = None,
stateless_http: bool | None = None,
stateless: bool | None = None,
host_origin_protection: HostOriginProtection | None = None,
allowed_hosts: list[str] | None = None,
allowed_origins: list[str] | None = None,
sockets: list[socket.socket] | None = None,
```

Note `streamable-http` is accepted as an alias of `http`. `allowed_hosts` / `allowed_origins` / `host_origin_protection` matter the moment we bind to `0.0.0.0` behind a proxy.

CLI:

```bash
fastmcp run server.py                                # STDIO
fastmcp run server.py --transport http --port 8080   # HTTP
fastmcp run server.py --reload                       # auto-reload
fastmcp run server.py --python 3.11 --with pandas    # ad-hoc deps
fastmcp run server.py -- --config config.json        # pass args to the server
```

---

## 7. Lifespan — survives 4.0, and the reference project's import is CORRECT

`fastmcp/server/lifespan.py` **exists in 4.0.0b4** (and in 3.4.7) and the `@lifespan` decorator import path `from fastmcp.server.lifespan import lifespan` is exactly what its own module docstring documents `[FROM SOURCE]`. Composition and teardown order are executed and confirmed on 4.0 **[FASTMCP-SPIKE-4.md §9.1]**:

```python
from fastmcp import FastMCP
from fastmcp.server.lifespan import lifespan

@lifespan
async def db_lifespan(server):
    conn = await connect_db()
    yield {"db": conn}
    await conn.close()

@lifespan
async def cache_lifespan(server):
    cache = await connect_cache()
    yield {"cache": cache}
    await cache.close()

mcp = FastMCP("server", lifespan=db_lifespan | cache_lifespan)
```

The point of the wrapper is the **`|` composition operator** — `ComposedLifespan` enters left then right, exits in reverse, and shallow-merges the yielded dicts. `fast-mcp-jira` uses `@lifespan` on a single monolithic function and never composes, so it pays the import for nothing, but it is not wrong.

To compose with a plain `@asynccontextmanager` lifespan, wrap it:

```python
from contextlib import asynccontextmanager
from fastmcp.server.lifespan import lifespan, ContextManagerLifespan

@asynccontextmanager
async def legacy_lifespan(server):
    yield {"legacy": True}

@lifespan
async def new_lifespan(server):
    yield {"new": True}

combined = ContextManagerLifespan(legacy_lifespan) | new_lifespan
```

`FastMCP(lifespan=...)` accepts `LifespanCallable | Lifespan | None`, so a bare `@asynccontextmanager` function also still works directly.

Whatever the lifespan yields is reachable from a tool via `ctx.lifespan_context`.

**Recommendation for `fast-mcp-template`:** one `@lifespan` per resource (HTTP client, cache), composed with `|`. Cleaner than the 60-line try/finally block in `fast-mcp-jira/server.py`.

---

## 8. Middleware, Context, error masking

### Middleware — from `https://gofastmcp.com/servers/middleware`

```python
from fastmcp.server.middleware import Middleware, MiddlewareContext

class CustomMiddleware(Middleware):
    async def on_request(self, context: MiddlewareContext, call_next):
        # Pre-processing logic
        result = await call_next(context)
        # Post-processing logic
        return result
```

```python
mcp = FastMCP("MyServer")
mcp.add_middleware(CustomMiddleware())
```

*"Middleware executes in the order added to the server. The first middleware runs first on the way in and last on the way out."*

Hooks by specificity: `on_message`; `on_request` / `on_notification`; `on_call_tool`, `on_read_resource`, `on_get_prompt`, `on_list_tools`, `on_list_resources`, `on_list_prompts`, `on_initialize`, `on_discover`.

Built-ins (modules confirmed present at `fastmcp/server/middleware/` `[FROM SOURCE]`: `authorization, caching, dereference, error_handling, logging, ping, rate_limiting, response_limiting, timing, tool_injection`):

| Middleware | Status for us **[FASTMCP-SPIKE-4.md §6, §13]** |
|---|---|
| `StructuredLoggingMiddleware` | ✅ safe — keep `include_payloads=False` (payloads are candidate PII) |
| `TimingMiddleware` | ✅ safe |
| `ResponseCachingMiddleware` | ✅ safe; tool-call caching is **opt-in** via `call_tool_settings` |
| `RetryMiddleware` | ⛔ **cannot exclude a tool** — no `tools=` parameter, hooks `on_request`, and it duplicated a non-idempotent write 4x in one call. Put retries in the Jobvite client instead **[FASTMCP-SPIKE-4.md §13.3]** |
| `RateLimitingMiddleware` | ✅ **adopt for D4**, with: explicit `get_client_id` (default keys everyone to `"global"`), burst sized `calls + 2`, restart-to-reconfigure (attribute mutation has no effect), and refusals arriving as raised `MCPError`s not problem objects **[FASTMCP-SPIKE-4.md §14.1]** |
| `ErrorHandlingMiddleware` | ⛔ **default `transform_errors=True` breaks the `ToolError` contract** — turns tool failures into raised `MCPError`s and relabels `ToolError` as "Internal error". Only usable with `transform_errors=False` |
| `ResponseLimitingMiddleware` | ⛔ **BROKEN** — truncation drops `structured_content` while the `outputSchema` remains, so the client raises. Cap sizes inside the tool instead |
| `PingMiddleware` | ➖ inert — the `ping` RPC does not exist on the sessionless era **[FASTMCP-SPIKE-4.md §14.4]** |
| `DereferenceMiddleware`, `ToolInjectionMiddleware`, `AuthorizationMiddleware` | ❓ untested — assume nothing |

Four of the eight exercised are unusable or need their defaults overridden. **Spike any middleware before adopting it.**

**Error-shape note:** RFC 9457 problem objects *returned* from a tool are unaffected by `ErrorHandlingMiddleware`, `transform_errors` and `mask_error_details` alike — they are the only error shape no configuration can distort, which argues for making them our primary error channel for expected conditions **[FASTMCP-SPIKE-4.md §14.2]**.

Access HTTP headers inside middleware via `get_http_headers()` from `fastmcp.server.dependencies`.

### Context

Public API of `fastmcp.Context` `[FROM SOURCE]`. ⚠️ This listing was enumerated on 3.4.7 and **not re-enumerated on 4.0.3**; its membership was verified in neither direction. A spot-check with `dir(fastmcp.Context)` on the installed 4.0.3 (2026-09-08) found the documented 4.0 removals (`sample`, `sample_step`, `list_roots`) gone AND three members the listing never mentions present (`client_extension_settings`, `input_responses`, `request_state`), so the known drift is six symbols, not three. Treat it as indicative, not authoritative:

```
client_id, client_supports_extension, close_sse_stream, debug, delete_state,
disable_components, elicit, enable_components, error, fastmcp, get_prompt,
get_state, info, is_background_task, lifespan_context, list_prompts,
list_resources, list_roots, log, origin_request_id, read_resource,
report_progress, request_context, request_id, reset_visibility, sample,
sample_step, send_notification, session, session_id, set_state, task_id,
transport, warning
```

Inject it by annotating a tool parameter `ctx: Context`. Logging: `ctx.debug/info/warning/error/log`. Progress: `await ctx.report_progress(...)`. Sampling: `ctx.sample` / `ctx.sample_step`. Elicitation: `ctx.elicit`. Per-request state: `ctx.get_state` / `ctx.set_state` / `ctx.delete_state`. Lifespan values: `ctx.lifespan_context`.

⚠️ `ctx.sample()`, `ctx.sample_step()` and `ctx.list_roots()` are **removed in 4.0** — as is `FastMCP(sampling_handler=...)`, confirmed by signature. `ctx.elicit()` requires `response_type` and is gated off on sessionless connections. Do not build anything load-bearing on them.

### Error masking

`FastMCP(mask_error_details=True)`; global default `False` `[FROM SOURCE]`; env override `FASTMCP_MASK_ERROR_DETAILS`.

---

## 9. Testing

From `https://gofastmcp.com/patterns/testing`:

```python
import pytest
from fastmcp.client import Client
from fastmcp.client.transports import FastMCPTransport

from my_project.main import mcp

@pytest.fixture
async def main_mcp_client():
    async with Client(transport=mcp) as mcp_client:
        yield mcp_client

async def test_list_tools(main_mcp_client: Client[FastMCPTransport]):
    list_tools = await main_mcp_client.list_tools()
    assert len(list_tools) == 5
```

Passing the `FastMCP` instance directly to `Client` runs entirely in memory — no subprocess, no socket. The docs frame it as *"a tight development loop by allowing you to avoid using a separate tool like MCP Inspector during development."*

`Client.__init__` signature `[FROM SOURCE]` accepts, besides `transport`: `name, roots, sampling_handler, sampling_capabilities, elicitation_handler, log_handler, message_handler, progress_handler, timeout, auto_initialize, init_timeout, client_info, auth, verify`. For auth-enabled servers under test, `auth="<token>"` sends it as a bearer token.

`fast-mcp-jira` has `pytest`/`pytest-asyncio` with `asyncio_mode = "auto"` in `pyproject.toml` but **no `tests/` directory on disk** — carry the config over, not the (absent) practice.

---

## 10. Deployment, packaging, CLI

### `fastmcp.json` (the real manifest)

Schema `$id`: `https://gofastmcp.com/public/schemas/fastmcp.json/v1.json`. Top-level: `source` (**required**), `environment`, `deployment` `[FROM SOURCE, schema.json]`.

```json
{
  "$schema": "https://gofastmcp.com/public/schemas/fastmcp.json/v1.json",
  "source": {
    "type": "filesystem",
    "path": "server.py",
    "entrypoint": "mcp"
  },
  "environment": {
    "type": "uv",
    "python": ">=3.10",
    "dependencies": ["pandas", "numpy"],
    "editable": ["."]
  },
  "deployment": {
    "transport": "stdio",
    "log_level": "INFO",
    "env": {
      "API_KEY": "secret-key",
      "DATABASE_URL": "postgres://${DB_USER}@${DB_HOST}/mydb"
    }
  }
}
```

- `source`: `type` is `"filesystem"` (default; `"git"` and `"cloud"` are described as future), plus `path` and `entrypoint`.
- `environment`: `type: "uv"`, with `python`, `dependencies`, `requirements`, `project`, `editable`.
- `deployment`: `transport`, `host`, `port`, `path`, `log_level`, `env`, `cwd`, `args`.
- `env` supports `${VAR_NAME}` interpolation from the process environment; *"Undefined variables remain as literal strings."*
- Auto-detected: a file named exactly `fastmcp.json` in the cwd is picked up by `fastmcp run`, `fastmcp dev inspector`, and `fastmcp inspect`. CLI args override config values. `--skip-env` / `--skip-source` bypass preparation steps.

**Absence, stated loudly:** there is **no `required: true` / "declare a required env var" feature** in `fastmcp.json`. `deployment.env` only *sets* values. Any "this server needs `JOBVITE_API_KEY`" contract must be enforced in our own settings layer (pydantic-settings with a required field is the right call), not in the manifest. The `env_vars` array in `fast-mcp-jira/mcp-server.json` is a bespoke invention that no FastMCP code reads.

### CLI (`fastmcp --help` `[FROM SOURCE]`)

```
auth          Authentication-related utilities and configuration.
call          Call a tool, read a resource, or get a prompt on an MCP server.
dev           Development tools for MCP servers
discover      Discover MCP servers configured in editor and project configs.
generate-cli  Generate a standalone CLI script from an MCP server.
inspect       Inspect an MCP server and display information or generate a JSON report.
install       Install MCP servers in various clients and formats.
list          List tools available on an MCP server.
project       Manage FastMCP projects
run           Run an MCP server or connect to a remote one.
tasks         Manage FastMCP background tasks using Docket
version       Display version information and platform details.
```

`fastmcp install` targets various clients/formats (subcommands under `fastmcp/cli/install/`). `fastmcp inspect` produces a JSON capability report — useful as a CI artifact.

---

## 11. Deprecations and breaking changes (3.x history, and what 4.0 changed)

### Within 3.x (3.1 → 3.4.7), from `https://gofastmcp.com/updates`

| Version | Change | Migration |
|---|---|---|
| 3.2.0 | `ToolResult(..., is_error=True)` now enables rich error handling **instead of raising exceptions** | If you relied on it raising, raise `ToolError` explicitly |
| 3.2.x | Background tasks re-scoped from **session** to **authorization context** (breaking) | Re-check any task-scoped state assumptions |
| 3.2.x | Parameter descriptions auto-extracted from docstrings | Free improvement; can drop redundant `Field(description=...)` |
| 3.3.0 | `fastmcp-slim` split out (client/transport without Starlette/Uvicorn/server stack) | Depend on `fastmcp` for servers, `fastmcp-slim` for pure clients |
| 3.3.0 | `MultiAuth`, `CodeMode`, search transforms, `@mcp.tool(run_in_thread=False)` added | Additive |
| 3.3.1 | *"Standalone component imports like `from fastmcp.tools import tool` no longer pull in the server stack"*; component-level auth/task primitives moved to utility modules **with backward-compatible re-exports** | No action in 3.x |
| 3.4.x | `fastmcp-remote` stdio↔HTTP bridge; HF/Google auth providers; Ed25519 JWKS; trusted-proxy SSRF support; Host/Origin validation compat restored | Additive |

**Nothing in the 3.1 → 3.4.7 window breaks the shape `fast-mcp-jira` uses.** Its problem is missed opportunity, not breakage.

### 3.x → 4.0, from `https://gofastmcp.com/getting-started/upgrading/from-fastmcp-3`

Environment floors: `pydantic >= 2.12`; Starlette 1.x (*"FastAPI 0.133.0 is the first release that admits Starlette 1.x"*); **`httpx` replaced by `httpx2`** (drop-in fork; `except httpx.` blocks silently catch nothing after upgrade — a serious footgun for a server like ours that wraps `httpx` and catches its exceptions).

Import moves:

| Old | New |
|---|---|
| `fastmcp.server.proxy` | `fastmcp.server.providers.proxy` |
| `fastmcp.server.openapi` | `FastMCP` + `OpenAPIProvider` from `fastmcp.server.providers.openapi` |
| `fastmcp.tools.tool`, `fastmcp.resources.resource`, `fastmcp.prompts.prompt` | `fastmcp.tools`, `fastmcp.resources`, `fastmcp.prompts` |
| `fastmcp.server.tasks` | `fastmcp.utilities.tasks` |
| `CachableToolResult` | `CacheableToolResult` (**no alias**) |
| `PromptToolMiddleware`, `ResourceToolMiddleware` | `PromptsAsTools`, `ResourcesAsTools` from `fastmcp.server.transforms` |

Removals / renames:
- `FastMCP.as_proxy(sub)` → `create_proxy(sub)`; `import_server()` → `mount()` (**not equivalent** — `mount` is live composition); `mount(prefix=)` → `mount(namespace=)`; `add_tool_transformation()` → `add_transform(ToolTransform(...))`; `remove_tool()` → `local_provider.remove_tool()` (raises `KeyError`).
- Tool `serializer=` removed → return `ToolResult`.
- **Tool `exclude_args=` removed** → inject with `Depends()` instead. (Worth knowing before we lean on `exclude_args`.)
- `FastMCP(sampling_handler=...)` removed.
- `ctx.sample()`, `ctx.sample_step()`, `ctx.list_roots()` removed from `Context`.
- `ctx.elicit()` now **requires** `response_type`, and does not reach a default client on sessionless `2026-07-28` connections.
- `FASTMCP_DECORATOR_MODE` / `settings.decorator_mode` removed.
- `McpError` construction: `raise McpError(code=-32000, message="...")` — the old positional `McpError(ErrorData(...))` raises `TypeError`.
- Resource-not-found wire code changed **`-32002` → `-32602`**.
- Templated resources reject `..` and absolute paths; exempt via `ResourceSecurity(exempt_params={...})`.
- Tasks moved to an extension: `mcp.add_extension(TasksExtension())` from `fastmcp_tasks`; `task=` only valid on tools.
- Middleware hooks now observe **every** inbound message, including notifications and unroutable requests.

Install (4.0 has been GA since 2026-08-31, so the prerelease recipe that used to sit here, with its `constraint-dependencies` on `fastmcp-slim`, is no longer needed):

```bash
pip install "fastmcp==4.0.3"
```

### Design rules for `fast-mcp-template` on 4.0

1. Never use `exclude_args=`, `serializer=`, `sampling_handler=`, `ctx.sample*`, `ctx.list_roots()` — all removed in 4.0, confirmed by signature.
2. If we call `ctx.elicit()`, always pass `response_type`.
3. Keep our HTTP client wrapper's `except httpx.*` clauses in **one module** so the `httpx2` swap is a single-file change.
4. Use `mcp.mount(namespace=...)` semantics from day one if we ever compose servers.
5. Pin `mcp` alongside `fastmcp`. The one 4.0 defect we found (§8, `ResponseLimitingMiddleware`) was a **regression caused by the `mcp` 1.x → 2.x bump underneath unchanged middleware code** — the characteristic hazard of early adoption.

---

---

## 12. CI and packaging for a public repo

Context: the repo is canonical at `evolvconsulting/fast-mcp-template`, **public**, mirrored to `Aztec03hub/fast-mcp-template`.

### (a) Official FastMCP CI / GitHub Actions recipe — **DOES NOT EXIST**

Reported as an absence, loudly. I enumerated the complete documentation index at `https://gofastmcp.com/llms.txt`. There is **no** page for CI, GitHub Actions, release automation, or publishing. The `deployment/` section contains exactly five pages:

- `https://gofastmcp.com/deployment/running-server.md`
- `https://gofastmcp.com/deployment/http.md`
- `https://gofastmcp.com/deployment/sandboxed-agents.md`
- `https://gofastmcp.com/deployment/prefect-horizon.md`
- `https://gofastmcp.com/deployment/server-configuration.md`

The only CI-adjacent page is `https://gofastmcp.com/development/contributing.md`, which covers the workflow for contributing **to FastMCP itself**, not for a downstream server.

`https://gofastmcp.com/deployment/http.md` says only: *"Your FastMCP server can run anywhere that supports Python web applications"* — Cloud VMs, container platforms, PaaS, edge, Kubernetes — with requirements *"Python 3.10+ support and the ability to expose an HTTP port"*, and *"Most providers will require you to package your server (requirements.txt, Dockerfile, etc.) according to their deployment format."* That is the entirety of the official guidance.

**Conclusion:** there is nothing to copy. Our CI is our own design. The one FastMCP-specific thing worth putting in CI is `fastmcp inspect`, which emits a JSON capability report — a good drift-detector artifact (fail the build if the tool list changes unexpectedly).

### (b) Registry — yes, but it is an **MCP** artifact, not a FastMCP one

There **is** an official registry: `registry.modelcontextprotocol.io`. FastMCP itself has zero involvement — `grep -rn "server\.json\|mcp-name\|registry.modelcontextprotocol"` over the installed fastmcp package returns **no hits** `[FROM SOURCE]`, and the docs index has no registry page.

⚠️ **Status: preview.** The registry docs carry a standing note: *"The MCP Registry is currently in preview. Breaking changes or data resets may occur before general availability."*

The metadata file is **`server.json`** — schema `https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json`. Source: `https://github.com/modelcontextprotocol/registry/blob/main/docs/reference/server-json/generic-server-json.md`.

A PyPI-flavoured example, adapted from the docs' own PyPI sample (`.../docs/modelcontextprotocol-io/package-types.mdx`):

```json
{
  "$schema": "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json",
  "name": "io.github.evolvconsulting/fast-mcp-template",
  "title": "Jobvite",
  "description": "MCP server for the Jobvite ATS REST API",
  "version": "0.1.0",
  "repository": {
    "url": "https://github.com/evolvconsulting/fast-mcp-template",
    "source": "github"
  },
  "packages": [
    {
      "registryType": "pypi",
      "registryBaseUrl": "https://pypi.org",
      "identifier": "fast-mcp-template",
      "version": "0.1.0",
      "transport": { "type": "stdio" },
      "environmentVariables": [
        {
          "name": "JOBVITE_API_KEY",
          "description": "Jobvite API key",
          "isRequired": true,
          "isSecret": true
        }
      ]
    }
  ]
}
```

`repository` requires `url` and `source` `[FROM SOURCE, server.schema.json]`; `subfolder` is available for monorepos; `id` (the GitHub numeric repo ID, `gh api repos/<owner>/<repo> --jq '.id'`) is optional and is described as guarding against *"repository resurrection attacks"*.

**Namespace and authentication** (`.../docs/modelcontextprotocol-io/authentication.mdx`):

| Auth method | Required `name` format |
|---|---|
| GitHub-based | `io.github.<username>/*` or `io.github.<orgname>/*` |
| domain-based (DNS TXT at the **apex**) | `com.example.*/*` |

🚩 **Decision needed from Phil / blocker:** *"To publish under an **organization** namespace (`io.github.<orgname>/*`), you must be an **Owner** of that organization. Ordinary org membership is no longer sufficient."* So `io.github.evolvconsulting/fast-mcp-template` requires **org Owner** rights on `evolvconsulting`. And for CI: *"If you authenticate with a Personal Access Token (for example in CI), the token must let the registry read your organization role"* — classic PAT needs `read:org`; fine-grained PAT needs **Organization permissions → Members → Read-only**. Without it, publishing **silently falls back to the personal namespace** rather than failing. The alternative is DNS auth on an evolv-owned apex domain, which would give a `com.evolv*/...` name.

Publishing flow uses the official `mcp-publisher` CLI (commands: `init`, `login`, `logout`, `publish`, `status`, `validate`); install via a GitHub release tarball or `brew install mcp-publisher`. The registry **hosts metadata only, not artifacts** — the package must be on PyPI first.

⚠️ **The GitHub Action on the Marketplace named "Publish MCP Server" is `OtherVibes/mcp-publish-action@v1` — a THIRD-PARTY action, not an official `modelcontextprotocol/*` one.** I could not find an official publishing action, and `docs/guides/publishing/github-actions.md` and `.github/workflows/publish-mcp.yml` in the registry repo both 404. A web search asserted an `mcp-publisher login github-oidc` mode exists for CI, but **I could not confirm it in the official authentication doc**, which documents only `login github` (device flow) and the DNS/KMS variants. Treat OIDC-in-CI as unverified; the documented CI path is a PAT.

**Recommendation:** registry publication is optional and the registry is in preview. Ship the repo and PyPI package first; add `server.json` + a release job later, once the namespace question is settled.

### (c) PyPI publishing — FastMCP docs are silent; the registry docs are not

FastMCP's own docs **never mention publishing your server to PyPI**. Absence noted.

The MCP Registry docs do, because PyPI is one of its supported package registries — and only `https://pypi.org` is accepted (no mirrors, no private indexes).

**PyPI ownership verification is unusual and worth knowing before we write the README** (`.../docs/modelcontextprotocol-io/package-types.mdx`):

> The MCP Registry verifies ownership of PyPI packages by checking for the existence of an `mcp-name: $SERVER_NAME` string in the package README (which becomes the package description on PyPI).

```markdown
# Database Query MCP Server

This MCP server executes SQL queries and manages database connections.

<!-- mcp-name: io.github.username/database-query-mcp -->
```

> The `mcp-name:` token must be followed by a boundary — a newline, whitespace, an HTML tag, or the comment close `-->`. Keep it on its own line or inside `<!-- … -->`; do not glue it directly to trailing characters such as a sentence-ending period.

So: **if we ever intend to register, the `mcp-name:` comment must be in `README.md` before the first PyPI upload**, because it is baked into the published package description. Cheap to add now, annoying to retrofit (needs a version bump).

Beyond that there is no MCP- or FastMCP-specific packaging metadata. Standard `pyproject.toml` applies. `fast-mcp-jira`'s hatchling + `[project.scripts]` layout is fine and should be carried over — with a `[project.scripts] fast-mcp-template = "fast_mcp_template.__main__:main"` console entry point, which is what makes `uvx fast-mcp-template` work for stdio clients.

### (d) stdio for local clients vs HTTP for hosted use

A public repo gets both audiences, and the docs address the split directly (`https://gofastmcp.com/deployment/http.md`):

- *"STDIO transport is perfect for local development and desktop applications."*
- *"to unlock the full potential of MCP—centralized services, multi-client access, and network availability—you need remote HTTP deployment."*
- Two hosted shapes: direct — `mcp.run(transport="http", host="0.0.0.0", port=8000)` — or an **ASGI app** for production (*"multiple workers and custom middleware"*).
- *"Authentication is **highly recommended** for remote MCP servers. Some LLM clients require authentication for remote servers and will refuse to connect without it."*

Note also that every `server.json` example in the registry docs uses `"transport": { "type": "stdio" }` — the registry's package model assumes a locally-executed package. `streamable-http` and `sse` are valid `transport_type` values, but a registry entry for a hosted URL is a different shape from a PyPI package entry.

**Recommendation for `fast-mcp-template`:** support **both from one codebase**, selected at runtime, and do not fork the server.

- Default to **stdio** when run with no transport argument, so `uvx fast-mcp-template` just works for Claude Desktop / Claude Code / Cursor users cloning a public repo.
- Select HTTP explicitly via env/flag for the hosted deployment.
- `fast-mcp-jira/__main__.py` **hardcodes** `mcp.run(transport="http", host=..., port=...)` with no stdio path at all. For a public repo that is the wrong default and locks out every local client. Make the transport configurable.
- Ship a `fastmcp.json` with `deployment.transport` so `fastmcp run` in the repo root does the right thing, and document the HTTP invocation separately.
- Turn auth **on** for the hosted deployment (see §5), and `mask_error_details=True`.
- Set `allowed_hosts` / `allowed_origins` when binding `0.0.0.0`.

### (e) Secrets — what the docs actually say, and what our `.env.example` must satisfy

The one explicit statement, from `https://gofastmcp.com/deployment/http.md`:

> "Production deployments should never hardcode sensitive information like API keys or authentication tokens. Instead, use environment variables to configure your server at runtime."

with the pattern `auth_token = os.environ.get("MCP_AUTH_TOKEN")` and the instruction to deploy *"with your secrets safely stored in environment variables."*

Two more, from source and from the registry docs:

- `StaticTokenVerifier`'s own docstring `[FROM SOURCE]`: **"WARNING: Never use this in production - tokens are stored in plain text!"** — i.e. build the token dict from env at startup; never a literal in a committed file.
- The registry's `server.json` marks secrets explicitly with **`"isSecret": true`** alongside `"isRequired": true`.

**How a server declares required env vars to a client — the honest answer, which differs by artifact:**

| Artifact | Can declare *required* env vars? |
|---|---|
| `fastmcp.json` | ❌ **No.** `deployment.env` only *sets* values, with `${VAR}` interpolation from the process environment. Undefined variables *"remain as literal strings"* — a silent failure mode. There is no `required` flag anywhere in the schema. |
| `server.json` (MCP Registry) | ✅ **Yes.** `packages[].environmentVariables[]` with `name`, `description`, `isRequired`, `isSecret`, `default`. This is **the** standard mechanism. |
| Our own code | ✅ pydantic-settings with a non-defaulted required field → fails fast at startup with a clear message. |

So: **`server.json` is the declaration to clients; pydantic-settings is the enforcement.** Do both. Do not invent a third.

🔎 **This retroactively explains `fast-mcp-jira/mcp-server.json`.** Its `env_vars` array with `name` / `required` / `sensitive` / `description` is a near-miss of `server.json`'s `environmentVariables` with `name` / `isRequired` / `isSecret` / `description`. It looks like a half-remembered `server.json` under a wrong filename with wrong key casing — which is why nothing reads it. For `fast-mcp-template`, write a real `server.json` against the published schema (and validate it with `mcp-publisher validate`) rather than reinventing the shape.

**Publishable-repo checklist:**

- `.env` in `.gitignore`; commit only `.env.example` with **empty or obviously-fake** values (`JOBVITE_API_KEY=`), never a redacted-looking real key.
- No secret defaults in `config.py` — required secrets are required fields, so startup fails loudly rather than running unauthenticated.
- `fastmcp.json` `deployment.env` uses `${VAR}` indirection only. Never a literal secret; the file is public.
- `server.json` (if/when we register) marks every credential `"isSecret": true, "isRequired": true`.
- Add secret scanning in CI — GitHub push protection plus e.g. `gitleaks`. **This is our call, not a FastMCP recommendation**; the docs say nothing about scanning.
- The mirror to `Aztec03hub/fast-mcp-template` doubles the blast radius of a committed secret and mirrors history. Whatever lands, lands twice.

## What I could NOT verify

- **The spec revision is no longer an open question.** It was resolved by execution: `server/discover` on 4.0.0b4 reports `supportedVersions: ["2026-07-28"]`, and a legacy client negotiates `2025-11-25` against the same server **[FASTMCP-SPIKE-4.md §3]**.
- **GitHub releases/CHANGELOG were not read directly.** `api.github.com/repos/jlowin/fastmcp/releases` returned a non-list payload (rate limit or the repo has moved — context7 redirects `/jlowin/fastmcp` to `/prefecthq/fastmcp`, suggesting an org transfer). The version/date table above is from the PyPI JSON API, which is authoritative for release timing; the change descriptions are from the official `gofastmcp.com/updates` page. **I did not cross-check the changelog against the git history.**
- **The 3.x → 4.0 migration table in §11 is still documentation-derived**, taken from the official upgrade guide. The items I executed are marked **[SPIKE]**; the rest (tasks, `Depends()`, `create_proxy`, `mount`, `OpenAPIProvider`) are unverified. The lifespan question that used to sit here **is resolved: `fastmcp.server.lifespan.lifespan` survives into 4.0** **[FASTMCP-SPIKE-4.md §2]**.
- **`IntrospectionTokenVerifier` import path** is quoted from the docs (`fastmcp.server.auth.providers.introspection`) and the module file exists `[FROM SOURCE]`, but I did not instantiate it or read its constructor.
- **`https://gofastmcp.com/deployment/testing` returns 404.** The testing content lives at `/patterns/testing`. If a `deployment/testing` page is referenced anywhere, it is stale.
- **The `fastmcp install` subcommand surface** was not enumerated beyond the top-level help line.
- **`fastmcp.json` `deployment` sub-schema** was read via the docs prose, not by dumping the `$defs/Deployment` object field-by-field. The key list is the docs' list.
- **No load/perf, no Docker/Cloud Run deployment guidance** was researched — out of scope for this brief.
- **No official FastMCP CI/GitHub Actions recipe exists** — this is an absence I searched for and did not find (full docs index at `gofastmcp.com/llms.txt`), not a gap in my research. Same for FastMCP guidance on publishing to PyPI, on the MCP Registry, and on secret scanning.
- **`mcp-publisher login github-oidc`**: asserted by a web search result, **not** found in the official `docs/modelcontextprotocol-io/authentication.mdx`, which documents only `login github` (device flow) and DNS/KMS variants. Unverified — do not build a CI job around it without checking `mcp-publisher --help` on the actual binary.
- **`OtherVibes/mcp-publish-action@v1`** is third-party; I did not audit it and do not endorse it. I found no official `modelcontextprotocol/*` publishing action.
- **The `server.json` schema was read at version `2025-12-11` via the registry repo's docs, and the full `$defs` were not enumerated field-by-field** — I fetched the `2025-09-29` schema JSON and read only its head. Validate any real `server.json` with `mcp-publisher validate` before trusting my example.
- **I did not verify whether Phil is an Owner of the `evolvconsulting` GitHub org**, which gates the `io.github.evolvconsulting/*` namespace.
- **The MCP Registry is explicitly in preview** ("Breaking changes or data resets may occur before general availability"), so all of §12(b) is a moving target.
- **I did not test any of this.** Nothing in §12 was executed — no `mcp-publisher` run, no CI job, no PyPI upload.
