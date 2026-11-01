# LogLens — local log diagnosis + resource discovery

This is a full refactor of the uploaded `loglens_cli.py`. It keeps the local
Ollama diagnosis workflow and optional Qdrant memory, but separates resource
discovery from diagnosis.

## What changed

- The LLM returns structured diagnosis JSON and **never returns URLs**.
- Official docs, courses and YouTube videos are retrieved independently.
- Documentation searches are restricted to known official technology domains
  where a mapping is available.
- Courses are searched on a curated set of course platforms.
- YouTube video metadata is retrieved with `yt-dlp` (no API key).
- Resource results are relevance-ranked and deduplicated.
- Documentation/course links are checked with HTTP requests. HTTP 403/429 and
  network failures are marked `verification_inconclusive`, not falsely called
  broken. YouTube results are marked `metadata_found` because YouTube often
  blocks automated availability checks.
- Qdrant memory is optional and disabled by default. Retrieved memory is
  explicitly treated as unverified context; model-generated diagnoses are not
  promoted as trusted fixes.
- A JSON report is written for later UI integration.

## Architecture

```text
Log input
   |
Local secret/PII sanitization
   |
Optional Qdrant retrieval (unverified clues)
   |
Ollama structured diagnosis (JSON; no URLs)
   |
Resource engine
   +-- Official documentation: DDGS + technology domain allowlist
   +-- Courses: DDGS + course-platform allowlist
   +-- Videos: yt-dlp YouTube search
   |
Relevance ranking + URL validation
   |
CLI report + loglens_report.json
   |
Optional Qdrant storage (unverified diagnosis only)
```

## Requirements

- Python 3.10 or newer (Python 3.11 recommended)
- Ollama installed and running locally
- `llama3.2` model (or another Ollama model that follows JSON instructions)
- Internet connection for resource discovery
- Qdrant is optional

## Setup

### 1. Create a virtual environment

Linux/macOS:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Windows PowerShell:

```powershell
py -3 -m venv .venv
.venv\Scripts\Activate.ps1
```

### 2. Install dependencies

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

If you do not want Qdrant memory yet, the base resource engine only needs
`ollama`, `python-dotenv`, `requests`, `ddgs`, and `yt-dlp`. You can install
only those five packages initially:

```bash
pip install ollama python-dotenv requests ddgs yt-dlp
```

### 3. Start Ollama and download the model

```bash
ollama serve
```

In another terminal:

```bash
ollama pull llama3.2
```

If Ollama is already running as a service, you do not need to start it again.

### 4. Configure environment

Linux/macOS:

```bash
cp .env.example .env
```

Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

Edit `.env` if needed. The default model is `llama3.2`. Qdrant is disabled by
default so the app can run without a database.

### 5. Run LogLens

```bash
python loglens_cli.py --log "Redis connection refused on localhost:6379"
```

Or:

```bash
python loglens_cli.py --file sample.log
```

A report is printed to the terminal and saved to `loglens_report.json`.

## Optional Qdrant memory

Start Qdrant locally using Docker:

```bash
docker run -d --name loglens-qdrant \
  -p 6333:6333 -p 6334:6334 \
  -v "$(pwd)/qdrant_storage:/qdrant/storage" \
  qdrant/qdrant
```

Then set this in `.env`:

```dotenv
QDRANT_ENABLED=true
QDRANT_HOST=localhost
QDRANT_PORT=6333
QDRANT_COLLECTION=loglens_kb
```

The vector store may create the collection on first use depending on the
installed LangChain/Qdrant versions. If collection initialization fails,
check the installed package versions and Qdrant logs. You can also use
Qdrant Cloud by setting `QDRANT_URL` and `QDRANT_API_KEY`.

**Memory safety:** this version stores the diagnosis as unverified model output.
It does not store resource URLs as authoritative references. Before using
historical fixes automatically in production, add a human approval or
successful-resolution feedback workflow.

## Free resource providers

| Resource type | Provider | API key |
|---|---|---|
| Documentation | `ddgs` search, restricted to official domains | No |
| Courses | `ddgs` search, restricted to course platforms | No |
| YouTube | `yt-dlp` YouTube search | No |

These are free-access approaches, not uptime guarantees. Search providers and
YouTube can change, rate-limit, block automated access, or alter page markup.
For a production deployment, consider replacing the provider adapters with
official APIs or a search service with an explicit SLA.

## Resource verification statuses

- `verified`: the URL responded with a successful HTTP status.
- `redirected`: the URL responded and redirected to a final destination.
- `verification_inconclusive`: network error or server restriction such as
  403/429; the resource is not labelled broken.
- `unavailable`: the URL returned a failure status and is excluded.
- `metadata_found`: yt-dlp returned a YouTube video ID and metadata. This does
  not prove the video will play in every region/account.
- `discovery_link_not_video`: fallback YouTube search page, not an individual
  video. It should not be presented as a verified video.

## Add another technology

Edit `TECH_DOMAINS` in `loglens/resource_engine.py`. Add the official
documentation hostname(s), not a broad search engine or community forum.

Example:

```python
TECH_DOMAINS["mytechnology"] = ["docs.vendor.example"]
```

Keep domains specific. A technology's official docs may live on a different
domain; verify the vendor's canonical docs domain before adding it.

## Important limitations / next production steps

1. DDGS is a community search library, not a guaranteed search API. Expect
   occasional rate limits or provider changes.
2. The course list is curated but course search results still need content
   relevance review. A platform domain alone does not prove a course is good.
3. HTTP reachability is not the same as semantic relevance. The score is a
   lightweight lexical ranking heuristic, not a trained relevance model.
4. Version detection is only as good as the log and local model's inference.
   Do not assume the latest docs apply to older versions.
5. The sanitizer is best-effort. Review logs for credentials and add patterns
   specific to your environment before processing sensitive production logs.
6. The sample code is a development baseline, not a production security
   boundary. Restrict network egress, set request limits, and review outbound
   URLs if logs or model output can influence search terms.

## Troubleshooting

- `ollama ... connection refused`: start Ollama (`ollama serve`) and verify
  `ollama list`.
- `model not found`: run `ollama pull llama3.2`, or update `OLLAMA_MODEL`.
- `No sufficiently relevant resource...`: broaden the search terms or add the
  correct official domain to `TECH_DOMAINS`.
- `verification_inconclusive`: the host may block automated requests. Open the
  URL manually; do not treat this status as a confirmed broken link.
- YouTube search fails: update `yt-dlp` with `pip install -U yt-dlp`.

## Example

```bash
python loglens_cli.py --log \
"2025-01-01 ERROR RedisConnectionException: Connection refused 127.0.0.1:6379"
```
