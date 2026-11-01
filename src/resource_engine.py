from __future__ import annotations

import logging
import os
import re
import time
from typing import Any
from urllib.parse import urlparse

import requests
from ddgs import DDGS

log = logging.getLogger("loglens.resources")

TECH_DOMAINS = {
    "redis": ["redis.io"],
    "postgresql": ["postgresql.org"],
    "postgres": ["postgresql.org"],
    "sql": ["postgresql.org"],
    "java": ["dev.java", "docs.oracle.com"],
    "spring": ["docs.spring.io"],
    "spring boot": ["docs.spring.io"],
    "kafka": ["kafka.apache.org"],
    "docker": ["docs.docker.com"],
    "container": ["docs.docker.com"],
    "kubernetes": ["kubernetes.io"],
    "k8s": ["kubernetes.io"],
    "python": ["docs.python.org"],
    "linux": ["kernel.org", "man7.org", "ubuntu.com", "access.redhat.com"],
    "nginx": ["nginx.org"],
    "terraform": ["developer.hashicorp.com"],
    "aws": ["docs.aws.amazon.com"],
    "azure": ["learn.microsoft.com"],
    "gcp": ["cloud.google.com"],
    "git": ["git-scm.com", "docs.github.com"],
    "github actions": ["docs.github.com"],
    "jenkins": ["www.jenkins.io"],
    "prometheus": ["prometheus.io"],
    "grafana": ["grafana.com"],
    "elasticsearch": ["elastic.co"],
    "opensearch": ["opensearch.org"],
    "mongodb": ["mongodb.com"],
    "mysql": ["dev.mysql.com"],
    "node": ["nodejs.org"],
    "node.js": ["nodejs.org"],
    "golang": ["go.dev"],
    "go": ["go.dev"],
}

COURSE_DOMAINS = [
    "coursera.org", "edx.org", "udemy.com", "linuxfoundation.org",
    " kodekloud.com", " pluralsight.com", "training.linuxfoundation.org",
]

COURSE_DOMAINS = [d.strip() for d in COURSE_DOMAINS]

TRUSTED_DOC_ROOTS = {
    "redis.io", "postgresql.org", "dev.java", "docs.oracle.com",
    "docs.spring.io", "kafka.apache.org", "docs.docker.com",
    "kubernetes.io", "docs.python.org", "kernel.org", "man7.org",
    "ubuntu.com", "access.redhat.com", "nginx.org",
    "developer.hashicorp.com", "docs.aws.amazon.com",
    "learn.microsoft.com", "cloud.google.com", "git-scm.com",
    "docs.github.com", "www.jenkins.io", "prometheus.io", "grafana.com",
    "elastic.co", "opensearch.org", "mongodb.com", "dev.mysql.com",
    "nodejs.org", "go.dev",
}


def _host(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower().removeprefix("www.")
    except Exception:
        return ""


def _is_domain(host: str, domains: list[str]) -> bool:
    return any(host == d.lower().removeprefix("www.") or
               host.endswith("." + d.lower().removeprefix("www."))
               for d in domains)


def _terms(text: str) -> set[str]:
    return {w.lower() for w in re.findall(r"[a-zA-Z0-9+#._-]{2,}", text)
            if w.lower() not in {"the", "and", "for", "with", "from", "error",
                                 "issue", "using", "that", "this", "not"}}


class ResourceEngine:
    def __init__(self) -> None:
        self.max_results = int(os.getenv("RESOURCE_RESULTS_PER_TYPE", "5"))
        self.timeout = int(os.getenv("RESOURCE_TIMEOUT", "10"))
        self.verify_links = os.getenv("VERIFY_RESOURCE_URLS", "true").lower() not in {
            "0", "false", "no"
        }
        self.user_agent = os.getenv(
            "RESOURCE_USER_AGENT",
            "Mozilla/5.0 (compatible; LogLens/1.0; resource-check)"
        )

    def _query(self, diagnosis: dict[str, Any]) -> str:
        technology = str(diagnosis.get("technology", "unknown")).strip()
        error = str(diagnosis.get("error_keyword", "")).strip()
        terms = diagnosis.get("search_terms", [])[:3]
        tags = diagnosis.get("tags", [])[:4]
        version = str(diagnosis.get("version", "")).strip()
        parts = [technology, error, *terms, *tags]
        if version:
            parts.append(version)
        return " ".join(str(x) for x in parts if x and str(x).lower() != "unknown")

    def _domains(self, technology: str) -> list[str]:
        tech = technology.lower()
        for key, domains in TECH_DOMAINS.items():
            if key in tech:
                return domains
        return []

    def _search(self, query: str, max_results: int = 5) -> list[dict]:
        try:
            # DDGS is a no-key search library; provider availability/rate limits vary.
            with DDGS(timeout=self.timeout) as ddgs:
                return list(ddgs.text(query, max_results=max_results))
        except Exception as exc:
            log.warning("Web search failed for %r: %s", query, exc)
            return []

    def _verify(self, url: str) -> tuple[str, str]:
        if not self.verify_links:
            return "not_checked", url
        if not url.startswith(("https://", "http://")):
            return "invalid_url", url
        try:
            response = requests.get(
                url, headers={"User-Agent": self.user_agent},
                timeout=self.timeout, allow_redirects=True, stream=True,
            )
            status = response.status_code
            final_url = response.url
            response.close()
            if 200 <= status < 400:
                return ("redirected" if final_url.rstrip("/") != url.rstrip("/")
                        else "verified"), final_url
            if status in (401, 403, 405, 429):
                return "verification_inconclusive", final_url
            return "unavailable", final_url
        except requests.RequestException:
            return "verification_inconclusive", url

    def _relevance(self, query: str, title: str, body: str, host: str,
                   category: str, trusted_domains: list[str]) -> float:
        q = _terms(query)
        content = _terms(f"{title} {body}")
        overlap = len(q & content) / max(1, len(q))
        authority = 0.18 if _is_domain(host, trusted_domains) else 0.0
        # Reward titles that contain the exact error category / core technology.
        title_terms = _terms(title)
        title_match = len(q & title_terms) / max(1, len(q))
        category_bonus = 0.08 if category == "documentation" and authority else 0.0
        return min(1.0, 0.62 * overlap + 0.20 * title_match + authority + category_bonus)

    def _normalize_search_result(self, item: dict, query: str, category: str,
                                 trusted_domains: list[str]) -> dict | None:
        url = str(item.get("href") or item.get("url") or "").strip()
        title = str(item.get("title") or "").strip()
        body = str(item.get("body") or item.get("snippet") or "").strip()
        host = _host(url)
        if not url.startswith("https://") or not title or not host:
            return None
        score = self._relevance(query, title, body, host, category, trusted_domains)
        if category == "documentation" and trusted_domains and not _is_domain(host, trusted_domains):
            return None
        if category == "courses" and not _is_domain(host, COURSE_DOMAINS):
            return None
        return {
            "title": title, "url": url, "source": host,
            "description": body, "score": round(score, 3),
            "verification": "pending",
        }

    def _retrieve_docs(self, query: str, technology: str) -> list[dict]:
        domains = self._domains(technology)
        if not domains:
            # For unknown technologies, search official docs only; do not silently
            # substitute Stack Overflow as "official documentation".
            search_query = f'{query} official documentation'
            trusted = []
        else:
            search_query = f'{query} (' + " OR ".join(f"site:{d}" for d in domains) + ")"
            trusted = domains
        raw = self._search(search_query, self.max_results * 3)
        candidates = []
        for item in raw:
            result = self._normalize_search_result(
                item, query, "documentation", trusted
            )
            if result:
                candidates.append(result)
        if not domains:
            # Unknown stack: retain only recognized official documentation domains.
            candidates = [
                r for r in candidates if _is_domain(r["source"], list(TRUSTED_DOC_ROOTS))
            ]
        return candidates

    def _retrieve_courses(self, query: str) -> list[dict]:
        site_query = " OR ".join(f"site:{d}" for d in COURSE_DOMAINS)
        raw = self._search(f'{query} course training ({site_query})',
                           self.max_results * 3)
        candidates = []
        for item in raw:
            result = self._normalize_search_result(
                item, query, "courses", COURSE_DOMAINS
            )
            if result:
                candidates.append(result)
        return candidates

    def _retrieve_videos(self, query: str) -> list[dict]:
        results: list[dict] = []
        try:
            import yt_dlp
            opts = {
                "quiet": True, "no_warnings": True, "skip_download": True,
                "extract_flat": True, "default_search": "ytsearch",
                "ignoreerrors": True,
            }
            with yt_dlp.YoutubeDL(opts) as ydl:
                data = ydl.extract_info(f"ytsearch{self.max_results}:{query} tutorial", download=False)
            for entry in (data or {}).get("entries", []) or []:
                if not entry:
                    continue
                video_id = entry.get("id")
                if not video_id:
                    continue
                url = f"https://www.youtube.com/watch?v={video_id}"
                title = str(entry.get("title") or "YouTube video")
                channel = str(entry.get("channel") or entry.get("uploader") or "Unknown channel")
                duration = entry.get("duration")
                description = f"Channel: {channel}"
                if duration:
                    description += f" | Duration: {int(duration) // 60} min"
                results.append({
                    "title": title, "url": url, "source": "youtube.com",
                    "description": description,
                    "score": round(self._relevance(
                        query, title, description, "youtube.com", "videos", ["youtube.com"]
                    ), 3),
                    "verification": "metadata_found",
                })
        except Exception as exc:
            log.warning("YouTube search unavailable (yt-dlp): %s", exc)
            # A search URL is a discovery fallback, not a verified individual video.
            from urllib.parse import quote_plus
            results.append({
                "title": f"YouTube search: {query}",
                "url": "https://www.youtube.com/results?search_query=" + quote_plus(query + " tutorial"),
                "source": "youtube.com",
                "description": "Search results page; no individual video was retrieved.",
                "score": 0.0,
                "verification": "discovery_link_not_video",
            })
        return results

    def _validate_rank(self, candidates: list[dict], category: str) -> list[dict]:
        output = []
        seen = set()
        minimum = float(os.getenv("MIN_RESOURCE_SCORE", "0.08"))
        for item in sorted(candidates, key=lambda x: x.get("score", 0), reverse=True):
            if item["url"] in seen or item.get("score", 0) < minimum:
                continue
            seen.add(item["url"])
            if category == "videos":
                # yt-dlp returned a real video ID. Do not issue a potentially
                # misleading "broken" status based on YouTube's bot protection.
                status, final_url = "metadata_found", item["url"]
            else:
                status, final_url = self._verify(item["url"])
            if status == "unavailable" or status == "invalid_url":
                continue
            item["verification"] = status
            item["url"] = final_url
            output.append(item)
            if len(output) >= self.max_results:
                break
            time.sleep(0.05)
        return output

    def find_resources(self, diagnosis: dict[str, Any]) -> dict[str, list[dict]]:
        query = self._query(diagnosis)
        technology = str(diagnosis.get("technology", "unknown"))
        if not query.strip():
            query = "software troubleshooting"

        docs = self._retrieve_docs(query, technology)
        courses = self._retrieve_courses(query)
        videos = self._retrieve_videos(query)

        return {
            "documentation": self._validate_rank(docs, "documentation"),
            "courses": self._validate_rank(courses, "courses"),
            "videos": self._validate_rank(videos, "videos"),
        }
