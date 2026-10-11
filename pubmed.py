"""NCBI E-utilities: reproducible searches and verbatim source metadata."""
import os
import time
import xml.etree.ElementTree as ET

import requests

BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
DEFAULT_QUERY = '(brain[Title/Abstract] OR "artificial intelligence"[Title/Abstract] OR "brain-computer interface"[Title/Abstract] OR "brain machine interface"[Title/Abstract]) AND english[Language]'


def node_text(node):
    return "" if node is None else "".join(node.itertext()).strip()


def parse_articles(xml):
    root = ET.fromstring(xml)
    results = []
    for entry in root.findall(".//PubmedArticle"):
        article = entry.find("./MedlineCitation/Article")
        if article is None:
            continue
        pmid = node_text(entry.find("./MedlineCitation/PMID"))
        ids = {x.attrib.get("IdType"): node_text(x) for x in entry.findall("./PubmedData/ArticleIdList/ArticleId")}
        parts = []
        for x in article.findall("./Abstract/AbstractText"):
            label = x.attrib.get("Label", "")
            parts.append((label + ": " if label else "") + node_text(x))
        authors = []
        for a in article.findall("./AuthorList/Author"):
            authors.append(node_text(a.find("CollectiveName")) or " ".join(filter(None, [node_text(a.find("ForeName")), node_text(a.find("LastName"))])))
        date = article.find("./Journal/JournalIssue/PubDate")
        publication_date = " ".join(node_text(x) for x in list(date)) if date is not None else ""
        results.append({"pmid": pmid, "doi": ids.get("doi", ""), "pmcid": ids.get("pmc", ""),
                        "title": node_text(article.find("ArticleTitle")), "abstract": "\n".join(parts),
                        "journal": node_text(article.find("./Journal/Title")), "date": publication_date,
                        "authors": authors, "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                        "publication_types": [node_text(x) for x in article.findall("./PublicationTypeList/PublicationType")],
                        "notices": [{"type": x.attrib.get("RefType", ""), "pmid": node_text(x.find("PMID"))} for x in entry.findall("./MedlineCitation/CommentsCorrectionsList/CommentsCorrections")],
                        "evidence_level": "abstract_only"})
    return results


class PubMed:
    def __init__(self):
        self.session = requests.Session()
        self.last_request = 0

    def get(self, endpoint, params):
        params = {"tool": "wechat_pubmed_local", **params}
        if os.getenv("NCBI_EMAIL"):
            params["email"] = os.environ["NCBI_EMAIL"]
        if os.getenv("NCBI_API_KEY"):
            params["api_key"] = os.environ["NCBI_API_KEY"]
        for attempt in range(3):
            time.sleep(max(0, 0.4 - (time.monotonic() - self.last_request)))
            self.last_request = time.monotonic()
            try:
                response = self.session.get(BASE + endpoint, params=params, timeout=45)
                if response.status_code == 429 or response.status_code >= 500:
                    time.sleep(2 ** attempt)
                    continue
                response.raise_for_status()
                return response
            except requests.RequestException:
                if attempt == 2:
                    break
                time.sleep(2 ** attempt)
        raise RuntimeError("NCBI 请求失败，请检查网络或稍后重试（凭据未写入错误信息）。")

    def search(self, query, limit=5, days=365):
        if not query.strip() or not 1 <= limit <= 100 or days < 0:
            raise ValueError("请输入检索式，结果数 1–100，时间范围不得为负；0 表示不限时间。")
        params = {"db": "pubmed", "term": query, "retmode": "json", "retmax": limit, "sort": "pub_date"}
        if days:
            params.update({"reldate": days, "datetype": "pdat"})
        raw = self.get("esearch.fcgi", params).json()
        if "error" in raw or "esearchresult" not in raw:
            raise RuntimeError("NCBI 检索返回异常。")
        result = raw["esearchresult"]
        if result.get("ERROR") or result.get("errorlist"):
            raise ValueError("NCBI 不接受此检索式，请检查字段和括号。")
        ids = result.get("idlist", [])
        records = self.fetch(ids) if ids else []
        by_id = {x["pmid"]: x for x in records}
        return {"query": query, "translation": result.get("querytranslation", ""), "count": int(result["count"]),
                "days": days, "warnings": result.get("warninglist", {}), "articles": [by_id[x] for x in ids if x in by_id]}

    def fetch(self, ids):
        if not ids or any(not str(x).isdigit() for x in ids):
            raise ValueError("PMID 必须为数字。")
        return parse_articles(self.get("efetch.fcgi", {"db": "pubmed", "id": ",".join(map(str, ids)), "retmode": "xml"}).content)
