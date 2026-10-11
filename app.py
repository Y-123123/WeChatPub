import io
import json
import os
import zipfile
from pathlib import Path

import streamlit as st

from clipboard import copy_html
from pipeline import OUTPUT, ROOT, attach_schematic, build, export, job, load_env, send, status, verify_draft
from pubmed import DEFAULT_QUERY, PubMed
from providers import configured
from settings import load_config, render_settings
from sources import search as source_search

load_env()
st.set_page_config(page_title="WeChatPub 公众号工作台", page_icon="📚", layout="wide")
st.title("WeChatPub 公众号工作台")
st.caption("本地检索 · 单篇中文解读 · 配图排版 · 微信文章包")
config = load_config()
render_settings()

with st.sidebar:
    st.subheader("接入状态")
    st.write("写作模型：" + ("已配置" if configured() else "未配置；只能生成资料卡"))
    st.write("微信 API：" + ("凭据已配置（权限待验证）" if os.getenv("WECHAT_APP_ID") and os.getenv("WECHAT_APP_SECRET") else "未接入"))
    st.info("默认模式为自动发布；需账号拥有素材、草稿及正式发布接口权限，也可选择草稿或预览。")
    st.code(str(ROOT / ".env"), language=None)
    st.caption("复制 .env.example 为 .env 后填写模型配置，重启工作台。密钥不在界面中显示。")
    if st.button("检查官方接口连接（只读）", disabled=not (os.getenv("WECHAT_APP_ID") and os.getenv("WECHAT_APP_SECRET"))):
        try:
            from wechat import WeChat
            st.json(WeChat().check())
        except (RuntimeError, ValueError) as error:
            st.error(str(error))

with st.form("search"):
    topic = st.text_input("栏目主题", config["topic"])
    query = st.text_area("PubMed 检索式（可以修改英文关键词及字段）", config["query"], height=90)
    c1, c2 = st.columns(2)
    limit = c1.number_input("返回文献数", 1, 100, 5)
    days = c2.number_input("最近多少天（0 = 不限时间）", 0, 36500, 365)
    search_clicked = st.form_submit_button("检索已配置英文来源", type="primary")
if search_clicked:
    try:
        with st.spinner("检索并获取原始摘要…"):
            st.session_state.results = source_search({**config, "query": query, "max_results": int(limit), "lookback_days": int(days)})
    except (ValueError, RuntimeError) as error:
        st.error(str(error))

results = st.session_state.get("results")
if results:
    st.write(f"匹配 {results['count']} 篇，显示 {len(results['articles'])} 篇。")
    st.caption("来源检索式：" + results["translation"])
    if results["warnings"]:
        st.warning(json.dumps(results["warnings"], ensure_ascii=False))
    st.download_button("下载检索结果 JSON", json.dumps(results, ensure_ascii=False, indent=2), "pubmed-search.json", "application/json")
    for source in results["articles"]:
        with st.expander(f"PMID {source['pmid']} · {source['title']}"):
            st.write(source["journal"] + " · " + source["date"])
            st.write("DOI: " + (source["doi"] or "未提供"))
            st.write(source["abstract"] or "无摘要")
            st.link_button("查看英文来源", source["url"])
            if st.button("生成这篇文献的文章包", key="generate-" + source["pmid"], disabled=not source["abstract"]):
                try:
                    with st.spinner("生成正文、核对证据摘录并制作配图…"):
                        folder = build(source, topic)
                    st.session_state.folder = str(folder)
                    st.success("文章包已保存。")
                except (RuntimeError, ValueError) as error:
                    st.error(str(error))
            ready = bool(source["abstract"] and configured() and os.getenv("WECHAT_APP_ID") and os.getenv("WECHAT_APP_SECRET"))
            if st.button("生成中文解读、配图并上传草稿", key="auto-draft-" + source["pmid"], disabled=not ready):
                try:
                    existing = None
                    from pipeline import db
                    with db() as conn:
                        existing = conn.execute("SELECT bundle FROM jobs WHERE account=? AND pmid=?", (os.getenv("WECHAT_APP_ID"), source["pmid"])).fetchone()
                    with st.spinner("生成文章、上传图片和草稿，并回读核验…"):
                        previous = Path(existing["bundle"]) if existing else None
                        old_article = json.loads((previous / "article.json").read_text(encoding="utf-8")) if previous else {}
                        folder = previous if old_article.get("style") == "deep_review" else build(source, topic)
                        st.session_state.folder = str(folder)
                        response = send(folder, replace_existing=True)
                    st.success("已保存到微信公众号草稿箱，正式发布请在后台完成。")
                    st.json({"media_id": response["media_id"], "stage": response["stage"]})
                except (RuntimeError, ValueError) as error:
                    st.error(str(error))

st.divider()
st.subheader("文章包与预览")
folders = sorted(OUTPUT.glob("*/article.json"), key=lambda x: x.stat().st_mtime, reverse=True) if OUTPUT.exists() else []
paths = [str(x.parent) for x in folders]
if paths:
    selected = st.session_state.get("folder", paths[0])
    folder = Path(st.selectbox("选择文章包", paths, index=paths.index(selected) if selected in paths else 0, format_func=lambda x: Path(x).name))
    article = json.loads((folder / "article.json").read_text(encoding="utf-8"))
    st.caption(str(folder))
    if not article.get("generated"):
        st.warning("当前是原始资料卡。配置 LLM_API_KEY 后重新生成，才能得到中文论文解读。")
    else:
        st.caption("编辑用证据摘录来自已读取的全文或摘要；上传草稿时不显示摘录。")
    c1, c2, c3 = st.columns(3)
    if c1.button("复制正文到 Windows 剪贴板"):
        try:
            copy_html((folder / "copy.html").read_text(encoding="utf-8"))
            st.success("正文已复制。在公众号编辑器粘贴后检查格式，图片请用下方文件单独上传。")
        except RuntimeError as error:
            st.error(str(error))
    c2.link_button("打开公众号后台", "https://mp.weixin.qq.com/")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as pack:
        names = ["source.json", "article.json", "manifest.json", "article.md", "article.html", "copy.html", "preview.html", "cover.jpg", "source-card.jpg", "imagegen-prompt.txt"] + [x["file"] for x in article.get("illustrations", [])]
        for name in names:
            if (folder / name).exists():
                pack.write(folder / name, name)
    c3.download_button("下载完整文章包", buffer.getvalue(), folder.name + ".zip", "application/zip")
    c1, c2 = st.columns(2)
    c1.download_button("下载封面", (folder / "cover.jpg").read_bytes(), "cover.jpg", "image/jpeg")
    for fig in article.get("illustrations", []):
        st.download_button("下载 " + fig.get("label", "科学配图"), (folder / fig["file"]).read_bytes(), fig["file"], "image/jpeg", key="download-" + fig["file"])
    with st.expander("加入 ImageGen 科学示意图"):
        st.caption("每篇文章包附有 imagegen-prompt.txt。可用该提示生成科学示意图，再导入到正文；原文图会保留。")
        if (folder / "imagegen-prompt.txt").exists():
            st.download_button("下载科学示意图提示词", (folder / "imagegen-prompt.txt").read_bytes(), "imagegen-prompt.txt", "text/plain")
        uploaded = st.file_uploader("导入生成的示意图", type=["png", "jpg", "jpeg"], key="schematic-" + folder.name)
        caption = st.text_input("示意图中文说明", "研究方法与证据关系示意", key="caption-" + folder.name)
        if st.button("保存示意图到文章", disabled=uploaded is None, key="attach-" + folder.name):
            try:
                attach_schematic(folder, uploaded.getvalue(), caption)
                st.rerun()
            except (ValueError, OSError) as error:
                st.error(str(error))
    st.html((folder / "preview.html").read_text(encoding="utf-8"))
    with st.expander("编辑文章 JSON（保留 evidence_quote，保存时会重新验证）"):
        with st.form("edit-" + folder.name):
            edited = st.text_area("正文结构", json.dumps(article, ensure_ascii=False, indent=2), height=400)
            save_clicked = st.form_submit_button("保存并重新导出")
        if save_clicked:
            try:
                from pipeline import save_json
                from writer import validate
                updated = json.loads(edited)
                source = json.loads((folder / "source.json").read_text(encoding="utf-8"))
                if updated.get("generated"):
                    validate(updated, source)
                save_json(folder / "article.json", updated)
                export(folder)
                st.success("已保存，刷新后查看新预览。")
            except (ValueError, RuntimeError) as error:
                st.error(str(error))
    with st.expander("微信公众号草稿箱"):
        st.caption("上传封面、正文配图和中文文章，回读核验后可直接调用正式发布接口。")
        enabled = bool(os.getenv("WECHAT_APP_ID") and os.getenv("WECHAT_APP_SECRET") and article.get("generated"))
        c1, c2 = st.columns(2)
        action = "draft" if c1.button("上传草稿", disabled=not enabled) else None
        if c2.button("核验草稿", disabled=not enabled):
            action = "verify"
        if action:
            try:
                with st.spinner("调用官方接口…"):
                    response = verify_draft(folder) if action == "verify" else send(folder, replace_existing=True)
                st.json(response)
                if action == "draft":
                    st.success("已上传到草稿箱并回读核验。")
            except (RuntimeError, ValueError) as error:
                st.error(str(error))
        current_job = job(folder)
        if current_job:
            st.json(current_job)
        if st.button("正式发布此文章包", disabled=not enabled):
            try:
                st.json(send(folder, publish=True))
            except (RuntimeError, ValueError) as error:
                st.error(str(error))
        if st.button("查询发布结果", disabled=not enabled):
            try:
                st.json(status(folder))
            except (RuntimeError, ValueError) as error:
                st.error(str(error))
else:
    st.caption("先检索并选择一篇文献生成文章包。")
