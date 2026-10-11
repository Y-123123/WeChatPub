"""Local configuration persistence; API keys are excluded from the repository."""
import json
import os
from pathlib import Path

from dotenv import set_key

from providers import PROVIDERS, configured, settings

ROOT = Path(__file__).resolve().parent


def load_config(path=None):
    path = Path(path) if path else ROOT / "config.json"
    if not path.exists():
        if path != ROOT / "config.json":
            raise ValueError("Configuration file not found.")
        path = ROOT / "config.example.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Configuration must be a JSON object.")
    return data


def save_settings(values, config):
    allowed = {"LLM_PROVIDER", "LLM_BASE_URL", "LLM_MODEL", "AUTO_PUBLISH", "WECHAT_APP_ID", "WECHAT_APP_SECRET", "NCBI_EMAIL", "NCBI_API_KEY", "WECHAT_AUTHOR"}
    allowed.update(x["key"] for x in PROVIDERS.values())
    for name, value in values.items():
        if name not in allowed or not isinstance(value, str) or "\n" in value or "\r" in value:
            raise ValueError("Invalid local setting.")
    path = ROOT / ".env"
    path.touch(exist_ok=True)
    try:
        path.chmod(0o600)
    except OSError:
        pass
    for name, value in values.items():
        set_key(str(path), name, value)
        os.environ[name] = value
    temp = ROOT / "config.json.tmp"
    temp.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(ROOT / "config.json")


def render_settings():
    import streamlit as st
    from pipeline import run
    config = load_config()
    current = settings()
    with st.expander("API 与自动发布设置 / API and automation"):
        with st.form("local-settings"):
            provider = st.selectbox("AI 服务 / Provider", list(PROVIDERS), index=list(PROVIDERS).index(current["provider"]), format_func=lambda x: PROVIDERS[x]["label"])
            st.caption("选择服务后填写该服务的模型 ID。Claude 使用原生 Messages API；其它服务使用 Chat Completions。")
            model = st.text_input("模型 ID / Model", current["model"])
            base = st.text_input("API 基础地址（空值使用服务默认） / Base URL", os.getenv("LLM_BASE_URL", ""))
            api_key = st.text_input("新 API key（留空保留所选服务已有 key）", type="password")
            appid = st.text_input("公众号 AppID（留空保留）")
            appsecret = st.text_input("公众号 AppSecret（留空保留）", type="password")
            topic = st.text_input("栏目主题 / Topic", config["topic"])
            selected_sources = st.multiselect("英文来源 / Sources", ["pubmed", "arxiv"], default=config.get("sources", ["pubmed", "arxiv"]))
            query = st.text_area("PubMed 检索式", config["query"])
            arxiv_query = st.text_area("arXiv 检索式", config.get("arxiv_query", ""))
            limit = st.number_input("每轮最多文章数", 1, 100, int(config.get("max_results", 3)))
            days = st.number_input("最近天数（0 不限）", 0, 36500, int(config.get("lookback_days", 30)))
            interval = st.number_input("自动任务间隔（小时）", 1.0, 168.0, float(config.get("interval_hours", 24)))
            mode = st.selectbox("流水线模式 / Mode", ["publish", "draft", "preview"], index=["publish", "draft", "preview"].index(config.get("mode", "publish")))
            st.caption("publish 会调用公众号正式发布接口。自动循环使用 python cli.py watch；网页不会在打开时自动发布。")
            saved = st.form_submit_button("保存到本地 / Save locally")
        if saved:
            values = {"LLM_PROVIDER": provider, "LLM_MODEL": model.strip() if provider == current["provider"] or model != current["model"] else PROVIDERS[provider]["model"],
                      "LLM_BASE_URL": base.strip(), "AUTO_PUBLISH": "true" if mode == "publish" else "false"}
            if api_key:
                values[PROVIDERS[provider]["key"]] = api_key.strip()
            if appid:
                values["WECHAT_APP_ID"] = appid.strip()
            if appsecret:
                values["WECHAT_APP_SECRET"] = appsecret.strip()
            config.update(topic=topic, query=query, arxiv_query=arxiv_query, sources=selected_sources,
                          max_results=int(limit), lookback_days=int(days), interval_hours=float(interval), mode=mode)
            if not selected_sources:
                st.error("请至少选择一个来源。")
            else:
                save_settings(values, config)
                st.success("已保存到 .env 与 config.json（均不会提交 GitHub）。")
                st.rerun()
        st.code("python cli.py watch", language="bash")
        if st.button("按已保存设置执行一轮 / Run one cycle", disabled=not configured()):
            try:
                with st.spinner("检索、生成、核对并执行流水线…"):
                    result = run(load_config())
                st.json(result)
            except (ValueError, RuntimeError, OSError) as error:
                st.error(str(error))
