import base64
import hashlib
import html
import json
import os
import re
import sqlite3
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from images import cards
from writer import write, validate
from wechat import WeChat
from providers import configured

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "output"
DATA = ROOT / "data"


def load_env():
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env", override=False)


def save_json(path, data):
    path = Path(path)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def esc(value):
    return html.escape(str(value), quote=True)


def render(source, article, image_url="source-card.jpg", audit=False, image_urls=None):
    illustrations = article.get("illustrations", [])
    image_urls = image_urls or {}
    def display_figure(fig):
        address = image_urls.get(fig["file"], fig["file"])
        credit = fig.get("attribution", "AI 辅助科学示意图")
        caption = fig.get("caption_zh") or fig.get("caption", "")
        return f'<p><img src="{esc(address)}" alt="{esc(fig.get("label", "研究示意图"))}" style="width:100%;height:auto;" /></p><p style="font-size:14px;">{esc(fig.get("label", "研究示意图"))} · {esc(caption)}</p><p style="font-size:12px;color:#65776f;">{esc(credit)}</p>'
    fulltext = source.get("evidence_level") == "full_text"
    parts = ['<section style="max-width:680px;margin:auto;padding:24px;font-family:Arial,sans-serif;color:#203e36;line-height:1.9;font-size:16px;">',
             f'<p style="color:#328b77;font-size:13px;">PUBMED · 单篇文献解读</p><h1 style="font-size:26px;">{esc(article["title"])}</h1>',
             f'<p style="background:#f1f5f1;padding:16px;">{esc(article["digest"])}</p>',
             '<p style="font-size:13px;color:#65776f;">' + ('主论文依据全文；相关研究比较依据摘要' if fulltext else '依据论文摘要与相关文献摘要整理') + ' · AI 辅助写作</p>']
    if not illustrations:
        parts.append(f'<img src="{esc(image_url)}" alt="文献信息" style="width:100%;height:auto;" />')
    shown = set()
    for fig in illustrations:
        if fig.get("kind") == "schematic":
            parts.append(display_figure(fig))
            shown.add(fig["file"])
    for section in article["sections"]:
        parts.append(f'<h2 style="font-size:21px;border-left:4px solid #328b77;padding-left:12px;">{esc(section["heading"])}</h2>')
        for paragraph in section["text"].split("\n"):
            if paragraph.strip():
                parts.append(f'<p>{esc(paragraph)}</p>')
        if audit and section.get("evidence_quote"):
            parts.append(f'<blockquote style="font-size:13px;color:#65776f;background:#f6f6f6;padding:12px;">来源证据：{esc(section["evidence_quote"])}</blockquote>')
        for fig in illustrations:
            if fig.get("id") in section.get("figure_ids", []) and fig["file"] not in shown:
                parts.append(display_figure(fig))
                shown.add(fig["file"])
    for fig in illustrations:
        if fig["file"] not in shown:
            parts.append(display_figure(fig))
    if source.get("references"):
        parts.append('<h2 style="font-size:20px;">参考文献</h2>')
        for index, reference in enumerate([source] + source["references"], 1):
            parts.append(f'<p style="font-size:13px;">[{index}] {esc(reference["title"])}. {esc(reference["journal"])} · {esc(reference["date"])}. DOI: {esc(reference["doi"])} · <a href="{esc(reference["url"])}">PMID {esc(reference["pmid"])}</a></p>')
    parts += ['<h2 style="font-size:20px;">原始文献</h2>', f'<p>{esc(source["title"])}<br>{esc(", ".join(source["authors"]))}<br>{esc(source["journal"])} · {esc(source["date"])}<br>来源 ID: {esc(source["pmid"])}<br>DOI: {esc(source["doi"] or "来源未提供")}</p>',
              f'<p><a href="{esc(source["url"])}">{esc(source.get("source_label", "PubMed"))} 原始记录</a></p>']
    if source["doi"]:
        from urllib.parse import quote
        parts.append(f'<p><a href="https://doi.org/{quote(source["doi"], safe="/")}">DOI 原文入口</a></p>')
    parts.append('</section>')
    return "\n".join(parts)


def build(source, topic):
    from research import enrich
    if source.get("source_type", "pubmed") == "pubmed":
        source = enrich(source)
    article = write(source, topic)
    return build_prepared(source, article, topic)


def build_prepared(source, article, topic):
    from research import download_figures
    OUTPUT.mkdir(exist_ok=True)
    folder = OUTPUT / (source["pmid"] + "-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:6])
    folder.mkdir()
    save_json(folder / "source.json", source)
    article["illustrations"] = download_figures(folder, source, max_count=5)
    for fig in article["illustrations"]:
        fig["caption_zh"] = article.get("figure_captions", {}).get(fig["id"], "")
    save_json(folder / "article.json", article)
    cards(folder, source, article["title"])
    export(folder)
    save_json(folder / "source.json", source)
    (folder / "imagegen-prompt.txt").write_text(article.get("schematic_prompt", ""), encoding="utf-8")
    save_json(folder / "manifest.json", {"created_utc": datetime.now(timezone.utc).isoformat(), "pmid": source["pmid"], "topic": topic, "evidence_level": source.get("evidence_level", "abstract_only"), "generated": article["generated"], "illustrations": [x["file"] for x in article["illustrations"]]})
    return folder


def export(folder):
    folder = Path(folder)
    source = json.loads((folder / "source.json").read_text(encoding="utf-8"))
    article = json.loads((folder / "article.json").read_text(encoding="utf-8"))
    if article.get("generated"):
        validate(article, source)
    image_data = base64.b64encode((folder / "source-card.jpg").read_bytes()).decode("ascii")
    inline = "data:image/jpeg;base64," + image_data
    embedded = {x["file"]: "data:image/jpeg;base64," + base64.b64encode((folder / x["file"]).read_bytes()).decode("ascii") for x in article.get("illustrations", [])}
    (folder / "article.html").write_text(render(source, article), encoding="utf-8")
    (folder / "copy.html").write_text(render(source, article, inline, image_urls=embedded), encoding="utf-8")
    (folder / "preview.html").write_text('<!doctype html><html lang="zh"><meta charset="utf-8"><title>文献解读预览</title>' + render(source, article, inline, audit=True, image_urls=embedded) + '</html>', encoding="utf-8")
    lines = ["# " + article["title"], article["digest"]]
    for fig in article.get("illustrations", []):
        if fig.get("kind") == "schematic":
            lines += [f'![{fig["label"]}]({fig["file"]})', fig.get("caption_zh", ""), fig.get("attribution", "")]
    for section in article["sections"]:
        lines += ["## " + section["heading"], section["text"]]
        for fig in article.get("illustrations", []):
            if fig.get("id") in section.get("figure_ids", []):
                lines += [f'![{fig["label"]}]({fig["file"]})', fig.get("caption_zh") or fig.get("caption", ""), fig.get("attribution", "")]
    for index, reference in enumerate(source.get("references", []), 2):
        lines += [f'[{index}] {reference["title"]}; DOI {reference["doi"]}; PMID {reference["pmid"]}; {reference["url"]}']
    lines += ["## 文献来源", source["title"], source["journal"] + " · " + source["date"], "PMID: " + source["pmid"], "DOI: " + source["doi"], source["url"]]
    (folder / "article.md").write_text("\n\n".join(lines), encoding="utf-8")


def attach_schematic(folder, image_bytes, caption):
    import io
    from PIL import Image
    folder = Path(folder)
    with Image.open(io.BytesIO(image_bytes)) as image:
        image.load()
        image = image.convert("RGB")
        image.thumbnail((2400, 2400))
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=92)
    if len(buffer.getvalue()) > 1_000_000:
        raise ValueError("示意图过大，请导入较小图片。")
    article = json.loads((folder / "article.json").read_text(encoding="utf-8"))
    (folder / "schematic.jpg").write_bytes(buffer.getvalue())
    article["illustrations"] = [{"id": "schematic", "file": "schematic.jpg", "kind": "schematic", "label": "研究思路总览", "caption_zh": caption, "attribution": "AI 辅助科学示意图"}] + [fig for fig in article.get("illustrations", []) if fig.get("kind") != "schematic"]
    save_json(folder / "article.json", article)
    export(folder)


@contextmanager
def db():
    DATA.mkdir(exist_ok=True)
    conn = sqlite3.connect(DATA / "state.sqlite", timeout=10)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE IF NOT EXISTS jobs (account TEXT, pmid TEXT, bundle TEXT, fingerprint TEXT, stage TEXT, cover_id TEXT, image_url TEXT, media_id TEXT, publish_id TEXT, result TEXT, PRIMARY KEY(account,pmid))")
        conn.execute("CREATE TABLE IF NOT EXISTS local_runs (pmid TEXT PRIMARY KEY, bundle TEXT)")
        if "uploaded_images" not in {row[1] for row in conn.execute("PRAGMA table_info(jobs)")}:
            conn.execute("ALTER TABLE jobs ADD COLUMN uploaded_images TEXT")
        conn.commit()
        with conn:
            yield conn
    finally:
        conn.close()


def fingerprint(folder):
    h = hashlib.sha256()
    for name in ("source.json", "article.json", "cover.jpg", "source-card.jpg"):
        h.update((folder / name).read_bytes())
    article = json.loads((folder / "article.json").read_text(encoding="utf-8"))
    for fig in article.get("illustrations", []):
        h.update((folder / fig["file"]).read_bytes())
    return h.hexdigest()


def job(folder):
    source = json.loads((Path(folder) / "source.json").read_text(encoding="utf-8"))
    account = os.getenv("WECHAT_APP_ID", "")
    with db() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE account=? AND pmid=?", (account, source["pmid"])).fetchone()
    return dict(row) if row else None


def update(account, pmid, **values):
    with db() as conn:
        conn.execute("UPDATE jobs SET " + ",".join(k + "=?" for k in values) + " WHERE account=? AND pmid=?", [*values.values(), account, pmid])


def claim(account, pmid, old_stage, new_stage):
    with db() as conn:
        result = conn.execute("UPDATE jobs SET stage=? WHERE account=? AND pmid=? AND stage=?", (new_stage, account, pmid, old_stage))
        if result.rowcount != 1:
            raise RuntimeError("任务正由其他进程处理，已停止重复操作。")


def draft_payload(source, article, cover, image_url, image_urls):
    return {"title": article["title"], "author": os.getenv("WECHAT_AUTHOR", "科研文献解读")[:16], "digest": article["digest"],
            "content": render(source, article, image_url, image_urls=image_urls), "content_source_url": source["url"], "thumb_media_id": cover, "need_open_comment": 0, "only_fans_can_comment": 0}


def upload_assets(client, folder, article):
    cover = client.upload_cover(folder / "cover.jpg")
    urls = {fig["file"]: client.upload_inline(folder / fig["file"]) for fig in article.get("illustrations", [])}
    image_url = next(iter(urls.values())) if urls else client.upload_inline(folder / "source-card.jpg")
    return cover, image_url, urls


def send(folder, publish=False, replace_existing=False):
    folder = Path(folder).resolve()
    source = json.loads((folder / "source.json").read_text(encoding="utf-8"))
    article = json.loads((folder / "article.json").read_text(encoding="utf-8"))
    if not article.get("generated"):
        raise ValueError("当前只有资料卡，没有生成中文解读，不能通过 API 上传或发布。")
    validate(article, source)
    client = WeChat()
    account, pmid, digest = client.appid, source["pmid"], fingerprint(folder)
    with db() as conn:
        conn.execute("INSERT OR IGNORE INTO jobs(account,pmid,bundle,fingerprint,stage) VALUES(?,?,?,?,?)", (account, pmid, str(folder), digest, "new"))
    state = job(folder)
    if state["fingerprint"] != digest:
        if replace_existing and not publish:
            return replace_draft(folder, client, state, source, article, digest)
        raise ValueError("此 PMID 已有另一版本的微信任务。请核查后台与原任务，不能直接重复发布。")
    if state["stage"] in ("uploading", "adding_draft", "submitting", "updating_assets", "updating_draft"):
        raise RuntimeError("上一请求正在执行或结果未知。请核查微信后台，再用 recover 恢复已知草稿/发布 ID。")
    if state["stage"] == "new":
        # Fetch token before marking mutation in-flight, so missing permissions/network are recoverable.
        client.access_token()
        claim(account, pmid, "new", "uploading")
        cover, image_url, urls = upload_assets(client, folder, article)
        update(account, pmid, stage="assets", cover_id=cover, image_url=image_url, uploaded_images=json.dumps(urls))
        state = job(folder)
    if state["stage"] == "assets":
        payload = draft_payload(source, article, state["cover_id"], state["image_url"], json.loads(state["uploaded_images"] or "{}"))
        save_json(folder / "wechat-payload.json", payload)
        claim(account, pmid, "assets", "adding_draft")
        media_id = client.add_draft(payload)
        update(account, pmid, stage="draft", media_id=media_id)
        state = job(folder)
    if publish and state["stage"] == "draft":
        verify_draft(folder, client)
        claim(account, pmid, "draft", "submitting")
        publish_id = client.submit(state["media_id"])
        update(account, pmid, stage="submitted", publish_id=str(publish_id))
    if not publish and state["stage"] == "draft":
        verify_draft(folder, client)
    return job(folder)


def replace_draft(folder, client, state, source, article, digest):
    if state["stage"] != "draft" or not state["media_id"]:
        raise ValueError("只有已核实的草稿可更新；当前任务状态不允许覆盖。")
    client.access_token()
    account, pmid = state["account"], state["pmid"]
    claim(account, pmid, "draft", "updating_assets")
    cover, image_url, urls = upload_assets(client, folder, article)
    payload = draft_payload(source, article, cover, image_url, urls)
    save_json(folder / "wechat-payload.json", payload)
    update(account, pmid, stage="updating_draft", bundle=str(folder), fingerprint=digest, cover_id=cover, image_url=image_url, uploaded_images=json.dumps(urls))
    client.update_draft(state["media_id"], payload)
    update(account, pmid, stage="draft")
    verify_draft(folder, client)
    with db() as conn:
        conn.execute("INSERT OR REPLACE INTO local_runs(pmid,bundle) VALUES(?,?)", (pmid, str(folder)))
    return job(folder)


def verify_draft(folder, client=None):
    state = job(folder)
    if not state or not state["media_id"]:
        raise ValueError("尚无可查询的微信草稿 ID。")
    result = (client or WeChat()).get_draft(state["media_id"])
    items = result.get("news_item", [])
    expected = json.loads((Path(folder) / "article.json").read_text(encoding="utf-8"))
    if not items or items[0].get("title") != expected["title"] or not items[0].get("content"):
        raise RuntimeError("草稿已提交，但回读校验不一致；请检查后台，勿重新上传。")
    returned_body = html.unescape(items[0]["content"])
    paragraphs = [p.strip() for section in expected["sections"] for p in section["text"].split("\n") if p.strip()]
    body_matches = all(p in returned_body for p in paragraphs)
    def image_identity(url):
        parsed = urlsplit(url)
        # WeChat rewrites http to https, src to data-src and /0 to /640.
        return parsed.netloc.lower(), parsed.path.rsplit("/", 1)[0]
    returned_images = re.findall(r'<img\b[^>]*\b(?:data-src|src)=[\"\']([^\"\']+)', returned_body)
    expected_urls = list(json.loads(state.get("uploaded_images") or "{}").values()) or [state["image_url"]]
    image_matches = all(any(image_identity(url) == image_identity(expected_url) for url in returned_images) for expected_url in expected_urls)
    cover_matches = items[0].get("thumb_media_id") == state["cover_id"]
    if not (body_matches and image_matches and cover_matches):
        raise RuntimeError("草稿已保存，但正文或配图回读不一致；请检查后台，勿重新上传。")
    verification = {"verified": True, "title": items[0]["title"], "body_matches": body_matches, "has_body_image": image_matches, "body_image_count": len(expected_urls), "cover_matches": cover_matches, "thumb_media_id": items[0].get("thumb_media_id", "")}
    save_json(Path(folder) / "wechat-verification.json", verification)
    update(state["account"], state["pmid"], result=json.dumps(verification, ensure_ascii=False))
    return verification


def status(folder):
    state = job(folder)
    if not state or not state["publish_id"]:
        raise ValueError("此文章尚无发布 ID。")
    if state["publish_id"].isdigit():
        publish_id = int(state["publish_id"])
    else:
        publish_id = state["publish_id"]
    result = WeChat().status(publish_id)
    code = result.get("publish_status")
    if code not in range(7):
        raise RuntimeError("微信返回未知发布状态。")
    stage = {0: "published", 1: "submitted", 2: "failed", 3: "failed", 4: "rejected", 5: "deleted", 6: "banned"}[code]
    update(state["account"], state["pmid"], stage=stage, result=json.dumps(result, ensure_ascii=False))
    return result


def recover(folder, media_id=None, publish_id=None):
    state = job(folder)
    if not state or state["stage"] not in ("uploading", "adding_draft", "submitting"):
        raise ValueError("只有结果未知的任务可恢复。")
    if publish_id:
        update(state["account"], state["pmid"], stage="submitted", publish_id=str(publish_id))
    elif media_id and state["stage"] in ("uploading", "adding_draft"):
        update(state["account"], state["pmid"], stage="draft", media_id=media_id)
    else:
        raise ValueError("须提供后台核实的 ID；提交发布结果未知时须提供 publish-id，不能退回草稿重发。")
    return job(folder)


def run(config):
    from locking import cycle_lock
    with cycle_lock(DATA / "runner.lock"):
        return _run(config)


def _run(config):
    from sources import search
    mode = config.get("mode", "publish")
    if mode not in ("preview", "draft", "publish"):
        raise ValueError("mode 须为 preview/draft/publish。")
    if mode == "publish" and os.getenv("AUTO_PUBLISH", "true").lower() != "true":
        raise ValueError("定期流水线发布须在本地 .env 设置 AUTO_PUBLISH=true；无接口权限请保持 preview。")
    if mode != "preview" and (not configured() or not os.getenv("WECHAT_APP_ID") or not os.getenv("WECHAT_APP_SECRET")):
        raise ValueError("Configure the selected model API and WeChat credentials before draft/publish mode.")
    results = search(config)
    DATA.mkdir(exist_ok=True)
    save_json(DATA / "last-search.json", {**results, "searched_utc": datetime.now(timezone.utc).isoformat()})
    report = []
    for source in results["articles"]:
        try:
            # Never regenerate already submitted/published content on a later cycle.
            if mode != "preview":
                with db() as conn:
                    previous = conn.execute("SELECT bundle, stage FROM jobs WHERE account=? AND pmid=?", (os.getenv("WECHAT_APP_ID", ""), source["pmid"])).fetchone()
                if previous and previous["stage"] in ("submitted", "published"):
                    result = {"pmid": source["pmid"], "folder": previous["bundle"], "stage": previous["stage"], "skipped": True}
                    if previous["stage"] == "submitted":
                        result["wechat"] = status(previous["bundle"])
                    report.append(result)
                    continue
            with db() as conn:
                row = conn.execute("SELECT bundle FROM local_runs WHERE pmid=?", (source["pmid"],)).fetchone()
            folder = Path(row["bundle"]) if row else build(source, config.get("topic", "科研文献解读"))
            if row and not folder.exists():
                raise ValueError("已生成的文章目录丢失，请核查本地记录。")
            article = json.loads((folder / "article.json").read_text(encoding="utf-8"))
            if row and not article.get("generated") and configured():
                folder = build(source, config.get("topic", "科研文献解读"))
                article = json.loads((folder / "article.json").read_text(encoding="utf-8"))
            if article.get("generated"):
                with db() as conn:
                    conn.execute("INSERT OR REPLACE INTO local_runs(pmid,bundle) VALUES(?,?)", (source["pmid"], str(folder)))
            result = {"pmid": source["pmid"], "folder": str(folder), "generated": article["generated"]}
            if mode != "preview":
                state = send(folder, publish=mode == "publish", replace_existing=mode == "draft")
                result["stage"] = state["stage"]
                if state["stage"] == "submitted":
                    result["wechat"] = status(folder)
            report.append(result)
        except (RuntimeError, ValueError, OSError) as error:
            report.append({"pmid": source["pmid"], "error": str(error)})
    save_json(DATA / "last-run.json", report)
    return report
