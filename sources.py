"""English scientific sources: PubMed plus arXiv Atom metadata/abstracts."""
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

import requests

from pubmed import DEFAULT_QUERY, PubMed

ARXIV_QUERY = '(all:brain OR all:"artificial intelligence" OR all:"brain-computer interface")'
ATOM = {"a": "http://www.w3.org/2005/Atom"}


def parse_arxiv(content, limit=5, days=30):
    tree = ET.fromstring(content)
    records = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=days) if days else None
    for entry in tree.findall("a:entry", ATOM):
        url = entry.findtext("a:id", default="", namespaces=ATOM)
        match = re.search(r"arxiv\.org/abs/([a-zA-Z0-9./-]+?)(?:v\d+)?$", url)
        if not match:
            continue
        date = entry.findtext("a:published", default="", namespaces=ATOM)
        if cutoff and date and datetime.fromisoformat(date.replace("Z", "+00:00")) < cutoff:
            continue
        records.append({"pmid": "arxiv-" + match[1].replace("/", "-"), "source_type": "arxiv", "source_label": "arXiv preprint",
                        "title": " ".join(entry.findtext("a:title", default="", namespaces=ATOM).split()),
                        "abstract": " ".join(entry.findtext("a:summary", default="", namespaces=ATOM).split()),
                        "authors": [x.text or "" for x in entry.findall("a:author/a:name", ATOM)],
                        "journal": "arXiv (preprint; not necessarily peer reviewed)", "date": date[:10], "doi": "",
                        "url": "https://arxiv.org/abs/" + match[1], "publication_types": ["Preprint"], "notices": [],
                        "evidence_level": "abstract_only", "references": [], "paper_figures": [],
                        "research_warnings": ["arXiv 预印本，未经本程序验证同行评审状态；仅依据摘要解读。"]})
        if len(records) >= limit:
            break
    return records


def search(config):
    selected = config.get("sources", ["pubmed", "arxiv"])
    if not selected or any(x not in ("pubmed", "arxiv") for x in selected):
        raise ValueError("sources must contain pubmed and/or arxiv.")
    limit, days = int(config.get("max_results", 3)), int(config.get("lookback_days", 30))
    if not 1 <= limit <= 100 or days < 0:
        raise ValueError("max_results must be 1–100; lookback_days must be nonnegative.")
    articles, warnings, translations, count = [], [], [], 0
    for name in selected:
        try:
            if name == "pubmed":
                result = PubMed().search(config.get("query", DEFAULT_QUERY), limit, days)
                for source in result["articles"]:
                    source["source_type"] = "pubmed"
                    source["source_label"] = "PubMed"
                articles.extend(result["articles"])
                count += result["count"]
                translations.append("PubMed: " + result["translation"])
                if result["warnings"]:
                    warnings.append(result["warnings"])
            else:
                query = config.get("arxiv_query", ARXIV_QUERY)
                response = requests.get("https://export.arxiv.org/api/query", params={"search_query": query, "start": 0, "max_results": limit, "sortBy": "submittedDate", "sortOrder": "descending"}, timeout=60)
                response.raise_for_status()
                found = parse_arxiv(response.content, limit, days)
                articles.extend(found)
                count += len(found)
                translations.append("arXiv: " + query)
        except (requests.RequestException, RuntimeError, ET.ParseError):
            warnings.append(name + " temporarily unavailable; retry on the next cycle.")
    if len(warnings) == len(selected) and not articles:
        raise RuntimeError("All selected sources unavailable; no publication attempted.")
    # Alternate sources so biomedical hits do not displace all AI preprints.
    groups = [[x for x in articles if x.get("source_type") == name] for name in selected]
    ordered = [group[i] for i in range(limit) for group in groups if i < len(group)][:limit]
    return {"articles": ordered, "count": count, "translation": "; ".join(translations), "warnings": warnings}
