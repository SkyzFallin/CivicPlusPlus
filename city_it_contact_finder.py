#!/usr/bin/env python3
"""
City IT Contact + Staff Directory Finder (single-file)

Input:  CSV with columns:
  - city
  - state
  - site_url
Optional:
  - county
  - known_directory_url

Outputs (in ./output):
  - staff_directory_candidates.csv
  - it_contacts.csv
  - clickup_import.csv
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
import tldextract


# ---------------------------
# Config
# ---------------------------
USER_AGENT = "city-it-contact-finder/1.0 (+https://github.com/yourname/yourrepo)"
DEFAULT_TIMEOUT = 20
SLEEP_S = 0.35

IT_KEYWORDS = [
    "information technology",
    " it ",
    "it-",
    "it/",
    "cio",
    "technology",
    "systems",
    "network",
    "computer",
    "help desk",
    "helpdesk",
    "gis",
]

TITLE_HINTS = [
    "it manager",
    "information technology manager",
    "director of it",
    "chief information officer",
    "cio",
    "it director",
    "technology director",
    "systems administrator",
    "network administrator",
]

PHONE_RE = re.compile(r"(\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}")
EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)


@dataclass
class FetchResult:
    url: str
    status: int
    text: str


# ---------------------------
# Helpers
# ---------------------------
def clean_whitespace(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def find_emails(text: str) -> list[str]:
    return sorted(set(EMAIL_RE.findall(text or "")))


def normalize_url(base: str, href: str) -> Optional[str]:
    if not href:
        return None
    href = href.strip()
    if href.startswith(("mailto:", "tel:", "javascript:")):
        return None
    full = urljoin(base, href)
    parsed = urlparse(full)
    return parsed._replace(fragment="").geturl()


def same_registrable_domain(url_a: str, url_b: str) -> bool:
    a = tldextract.extract(url_a)
    b = tldextract.extract(url_b)
    return (a.domain, a.suffix) == (b.domain, b.suffix)


def fetch(url: str, session: requests.Session, sleep_s: float = SLEEP_S) -> Optional[FetchResult]:
    time.sleep(sleep_s)
    try:
        resp = session.get(
            url,
            headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
            timeout=DEFAULT_TIMEOUT,
            allow_redirects=True,
        )
        ct = (resp.headers.get("Content-Type") or "").lower()
        if "text/html" not in ct and "application/xhtml+xml" not in ct:
            return None
        return FetchResult(url=resp.url, status=resp.status_code, text=resp.text or "")
    except requests.RequestException:
        return None


def score_directory_url(url: str) -> int:
    u = (url or "").lower()
    score = 0
    patterns = [
        "directory.aspx",
        "/directory",
        "staff-directory",
        "staffdirectory",
        "staff_directory",
        "/staff",
        "contact-directory",
        "directorylisting",
        "employee",
        "phonebook",
        "departments",
        "government",
        "city-hall",
    ]
    for p in patterns:
        if p in u:
            score += 15

    # slight bonus for "contact" pages
    if "contact" in u:
        score += 3

    # penalize likely irrelevant
    bad = ["pdf", "calendar", "news", "agenda", "minutes", "events", "privacy", "accessibility"]
    for b in bad:
        if b in u:
            score -= 5

    return score


def looks_it_related(text: str) -> bool:
    t = (text or "").lower()
    return any(k in t for k in IT_KEYWORDS) or any(h in t for h in TITLE_HINTS)


# ---------------------------
# Directory discovery
# ---------------------------
def discover_staff_directory(
    site_url: str,
    session: requests.Session,
    max_pages: int = 18,
    max_depth: int = 2,
) -> list[tuple[str, int]]:
    """
    Crawl a small portion of the site and return ranked directory candidates: [(url, score), ...]
    """
    site_url = clean_whitespace(site_url)
    if not site_url:
        return []
    if not site_url.endswith("/"):
        site_url += "/"

    visited: set[str] = set()
    q = deque([(site_url, 0)])
    candidates: dict[str, int] = {}

    while q and len(visited) < max_pages:
        url, depth = q.popleft()
        if url in visited or depth > max_depth:
            continue
        visited.add(url)

        fr = fetch(url, session=session)
        if not fr or fr.status >= 400 or not fr.text:
            continue

        # score the current page
        cur_score = score_directory_url(fr.url)
        if cur_score > 0:
            candidates[fr.url] = max(candidates.get(fr.url, 0), cur_score)

        soup = BeautifulSoup(fr.text, "lxml")

        for a in soup.select("a[href]"):
            full = normalize_url(fr.url, a.get("href"))
            if not full:
                continue

            scheme = urlparse(full).scheme.lower()
            if scheme not in ("http", "https"):
                continue

            if not same_registrable_domain(site_url, full):
                continue

            link_score = score_directory_url(full)
            if link_score > 0:
                candidates[full] = max(candidates.get(full, 0), link_score)

            # crawl limited, only if likely nav-ish
            if full not in visited and depth + 1 <= max_depth:
                nav_keywords = ["contact", "government", "departments", "services", "directory", "staff", "city-hall"]
                if any(k in full.lower() for k in nav_keywords):
                    q.append((full, depth + 1))

    return sorted(candidates.items(), key=lambda x: x[1], reverse=True)


# ---------------------------
# Contact extraction
# ---------------------------
def extract_contacts_from_html(html: str, page_url: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "lxml")
    page_text = soup.get_text(" ", strip=True)

    # If there are no IT keywords anywhere, avoid false positives
    if not looks_it_related(page_text):
        return []

    results: list[dict[str, Any]] = []

    # Structured scan: table rows
    for tr in soup.select("tr"):
        row_text = clean_whitespace(tr.get_text(" ", strip=True))
        if not looks_it_related(row_text):
            continue

        row_html = str(tr)
        row_emails = find_emails(row_html) or find_emails(row_text)
        row_phones = sorted(set(m.group(0) for m in PHONE_RE.finditer(row_text)))

        results.append(
            {
                "source_url": page_url,
                "context": row_text[:500],
                "emails": ", ".join(sorted(set(row_emails))),
                "phones": ", ".join(row_phones),
            }
        )

    # Cards / list items / common directory classes
    for el in soup.select("li, .card, .directory, .directory-item, .employee, .staff"):
        el_text = clean_whitespace(el.get_text(" ", strip=True))
        if not looks_it_related(el_text):
            continue
        el_html = str(el)
        el_emails = find_emails(el_html) or find_emails(el_text)
        el_phones = sorted(set(m.group(0) for m in PHONE_RE.finditer(el_text)))

        results.append(
            {
                "source_url": page_url,
                "context": el_text[:500],
                "emails": ", ".join(sorted(set(el_emails))),
                "phones": ", ".join(el_phones),
            }
        )

    # Fallback: if IT keywords exist, return page-level emails/phones
    if not results:
        emails = find_emails(html)
        phones = sorted(set(m.group(0) for m in PHONE_RE.finditer(page_text)))
        if emails or phones:
            results.append(
                {
                    "source_url": page_url,
                    "context": "Page contains IT-related keywords; extracted page-level emails/phones.",
                    "emails": ", ".join(emails),
                    "phones": ", ".join(phones),
                }
            )

    # de-dupe
    seen = set()
    deduped = []
    for r in results:
        key = (r["source_url"], r["emails"], r["phones"], r["context"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)
    return deduped


def extract_it_contacts(directory_url: str, session: requests.Session) -> list[dict[str, Any]]:
    fr = fetch(directory_url, session=session)
    if not fr or fr.status >= 400 or not fr.text:
        return []
    return extract_contacts_from_html(fr.text, fr.url)


# ---------------------------
# CSV IO
# ---------------------------
def read_csv(path: str) -> list[dict[str, str]]:
    with open(path, "r", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(path: str, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fieldnames})


# ---------------------------
# Main
# ---------------------------
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="Input CSV path (e.g. data/cities.csv)")
    ap.add_argument("--outdir", default="output", help="Output directory")
    ap.add_argument("--max_candidates", type=int, default=5, help="Directory candidates per city to keep")
    ap.add_argument("--max_pages", type=int, default=18, help="Pages to crawl per city (limit)")
    ap.add_argument("--max_depth", type=int, default=2, help="Crawl depth per city")
    args = ap.parse_args()

    session = requests.Session()

    cities = read_csv(args.input)

    directory_rows: list[dict[str, Any]] = []
    it_rows: list[dict[str, Any]] = []
    clickup_rows: list[dict[str, Any]] = []

    for c in cities:
        city = clean_whitespace(c.get("city", ""))
        state = clean_whitespace(c.get("state", ""))
        county = clean_whitespace(c.get("county", ""))
        site_url = clean_whitespace(c.get("site_url", ""))
        known_dir = clean_whitespace(c.get("known_directory_url", ""))

        if not site_url:
            continue

        if known_dir:
            ranked = [(known_dir, 999)]
            best_dir = known_dir
        else:
            ranked = discover_staff_directory(site_url, session=session, max_pages=args.max_pages, max_depth=args.max_depth)
            ranked = ranked[: args.max_candidates]
            best_dir = ranked[0][0] if ranked else ""

        # record directory candidates
        if ranked:
            for url, score in ranked:
                directory_rows.append(
                    {
                        "city": city,
                        "state": state,
                        "county": county,
                        "site_url": site_url,
                        "directory_candidate_url": url,
                        "score": score,
                        "chosen_best": "yes" if url == best_dir else "",
                    }
                )
        else:
            directory_rows.append(
                {
                    "city": city,
                    "state": state,
                    "county": county,
                    "site_url": site_url,
                    "directory_candidate_url": "",
                    "score": "",
                    "chosen_best": "",
                }
            )

        # extract IT contacts from best directory
        if best_dir:
            contacts = extract_it_contacts(best_dir, session=session)
            if contacts:
                for r in contacts:
                    it_rows.append(
                        {
                            "city": city,
                            "state": state,
                            "county": county,
                            "site_url": site_url,
                            "directory_url": best_dir,
                            "source_url": r.get("source_url", ""),
                            "emails": r.get("emails", ""),
                            "phones": r.get("phones", ""),
                            "context": r.get("context", ""),
                        }
                    )

                    clickup_rows.append(
                        {
                            "Task Name": f"{city}, {state} — IT contact",
                            "Description": f"Directory: {best_dir}\nSource: {r.get('source_url','')}\nEmails: {r.get('emails','')}\nPhones: {r.get('phones','')}\nContext: {r.get('context','')}",
                            "Status": "to do",
                            "City": city,
                            "State": state,
                            "County": county,
                            "Directory URL": best_dir,
                        }
                    )
            else:
                it_rows.append(
                    {
                        "city": city,
                        "state": state,
                        "county": county,
                        "site_url": site_url,
                        "directory_url": best_dir,
                        "source_url": "",
                        "emails": "",
                        "phones": "",
                        "context": "No IT-related contacts detected on best directory candidate.",
                    }
                )
        else:
            it_rows.append(
                {
                    "city": city,
                    "state": state,
                    "county": county,
                    "site_url": site_url,
                    "directory_url": "",
                    "source_url": "",
                    "emails": "",
                    "phones": "",
                    "context": "No staff directory page discovered.",
                    }
                )

    # write outputs
    outdir = args.outdir
    write_csv(
        os.path.join(outdir, "staff_directory_candidates.csv"),
        directory_rows,
        ["city", "state", "county", "site_url", "directory_candidate_url", "score", "chosen_best"],
    )
    write_csv(
        os.path.join(outdir, "it_contacts.csv"),
        it_rows,
        ["city", "state", "county", "site_url", "directory_url", "source_url", "emails", "phones", "context"],
    )
    if clickup_rows:
        write_csv(
            os.path.join(outdir, "clickup_import.csv"),
            clickup_rows,
            ["Task Name", "Description", "Status", "City", "State", "County", "Directory URL"],
        )

    print(f"Done. Outputs in: {outdir}/")


if __name__ == "__main__":
    main()
