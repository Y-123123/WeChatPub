"""Primary full text and permitted figure assets via the PMC Cloud Service."""
import io
import re
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlsplit, unquote

import requests
from PIL import Image
from pubmed import PubMed, node_text

BUCKET = "https://pmc-oa-opendata.s3.amazonaws.com/"
NS = {"s": "http://s3.amazonaws.com/doc/2006-03-01/"}


def cloud_get(url, params=None):
    if url.startswith("s3://pmc-oa-opendata/"):
        url = url.replace("s3://pmc-oa-opendata/", BUCKET, 1)
    if urlsplit(url).hostname != "pmc-oa-opendata.s3.amazonaws.com":
        raise ValueError("PMC 文件必须来自官方云存储。")
    r = requests.get(url, params=params, timeout=60)
    r.raise_for_status()
    return r


def parse_fulltext(xml):
    root = ET.fromstring(xml)
    article = root if root.tag == "article" else root.find(".//article")
    if article is None:
        raise ValueError("未找到 PMC article 节点。")
    body = article.find("body")
    texts = [node_text(x) for x in body.iter() if x.tag in ("title", "p", "caption", "table-wrap")] if body is not None else []
    figures = []
    for fig in article.findall(".//fig"):
        graphics = fig.findall(".//graphic")
        if graphics:
            figures.append({"id": fig.get("id", ""), "label": node_text(fig.find("label")), "caption": node_text(fig.find("caption")),
                            "filename": graphics[0].get("{http://www.w3.org/1999/xlink}href", ""),
                            "credit": node_text(fig.find("permissions"))})
    return {"fulltext": "\n\n".join(texts), "paper_figures": figures, "license_text": node_text(article.find("./front/article-meta/permissions"))}


def enrich(source):
    result = dict(source)
    result.update({"references": [], "research_warnings": [], "paper_figures": []})
    pmcid = source.get("pmcid", "")
    if re.fullmatch(r"PMC\d+", pmcid):
        try:
            listing = ET.fromstring(cloud_get(BUCKET, {"list-type": 2, "prefix": pmcid + ".", "delimiter": "/"}).content)
            prefixes = [x.text for x in listing.findall("s:CommonPrefixes/s:Prefix", NS)]
            candidates = []
            for prefix in prefixes[:6]:
                metadata = cloud_get(BUCKET + prefix + prefix.rstrip("/") + ".json").json()
                if metadata.get("is_retracted") in (True, "yes", "true"):
                    continue
                candidates.append((metadata.get("is_manuscript") in (True, "yes", "true"), prefix, metadata))
            if candidates:
                _, prefix, metadata = sorted(candidates, key=lambda x: x[0])[0]
                xml = cloud_get(metadata["xml_url"]).content
                details = parse_fulltext(xml)
                result.update(details)
                result["fulltext_xml"] = xml.decode("utf-8")
                result["cloud_metadata"] = metadata
                result["evidence_level"] = "full_text" if details["fulltext"] else "abstract_only"
                media = {unquote(urlsplit(url).path.rsplit("/", 1)[-1]): url for url in metadata.get("media_urls", [])}
                code = str(metadata.get("license_code", "")).lower().replace("_", "-").replace(" ", "-")
                # Conservative automatic reuse: unmodified CC-BY or public domain only.
                allowed = code in ("cc-by", "cc0", "cc-by-4.0", "cc-by-3.0")
                for fig in result["paper_figures"]:
                    fig["download_url"] = media.get(fig["filename"], "")
                    fig["license"] = metadata.get("license_code", "")
                    fig["reusable"] = allowed and bool(fig["download_url"]) and not fig["credit"]
                if not allowed:
                    result["research_warnings"].append("全文可读，但原图许可不符合自动转载条件。")
        except (requests.RequestException, ValueError, KeyError, ET.ParseError):
            result["research_warnings"].append("PMC 全文获取失败；按摘要范围解读。")
    client = PubMed()
    try:
        raw = client.get("elink.fcgi", {"dbfrom": "pubmed", "db": "pubmed", "id": source["pmid"], "linkname": "pubmed_pubmed", "retmode": "xml"}).content
        tree = ET.fromstring(raw)
        ids = [node_text(x) for x in tree.findall(".//LinkSetDb/Link/Id") if node_text(x) != source["pmid"]][:4]
        if ids:
            result["references"] = [x for x in client.fetch(ids) if x["abstract"] and "Retracted Publication" not in x["publication_types"] and not any(n["type"] in ("RetractionIn", "ExpressionOfConcernIn") for n in x["notices"])]
        result["related_search"] = {"method": "NCBI PubMed similar articles (pubmed_pubmed)", "seed_pmid": source["pmid"], "pmids": ids}
    except (requests.RequestException, RuntimeError, ValueError, ET.ParseError):
        result["research_warnings"].append("相关文献检索失败，不加入外部比较。")
    return result


def download_figures(folder, source, max_count=3):
    figures = []
    originals = source.get("paper_figures", [])
    # Keep methods, quantitative readout and perturbation panels when available.
    preferred = [x for x in originals if x["id"] in ("fig1", "fig3", "fig4", "fig5")]
    for original in preferred + [x for x in originals if x not in preferred]:
        if not original.get("reusable"):
            continue
        if len(figures) >= max_count:
            break
        try:
            data = cloud_get(original["download_url"]).content
            picture = Image.open(io.BytesIO(data))
            picture.load()
            # Conversion preserves the full panel; no cropping or data manipulation.
            name = "paper-" + re.sub(r"[^a-zA-Z0-9_-]", "", original["id"]) + ".jpg"
            picture.convert("RGB").save(Path(folder) / name, quality=95)
            figures.append({**original, "file": name, "kind": "paper", "source_url": source["url"],
                            "attribution": f"{source['authors'][0] if source['authors'] else 'Authors'} et al., {source['journal']}, {source['date']}; DOI {source['doi']}; {original['license']}"})
        except (requests.RequestException, OSError, ValueError):
            source["research_warnings"].append("原图 " + original["label"] + " 下载失败。")
    return figures
