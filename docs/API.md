# Model and WeChat API setup · 接口设置

Select `LLM_PROVIDER` in `.env`, or use the local settings panel. The following defaults are editable; use a model ID that your API account supports.

| Provider / 服务 | `LLM_PROVIDER` | Key variable / 密钥变量 | Default API base | Model |
|---|---|---|---|---|
| ChatGPT / OpenAI | `openai` | `OPENAI_API_KEY` | `https://api.openai.com/v1` | `OPENAI_MODEL`, preset `gpt-4.1-mini` |
| Gemini | `gemini` | `GEMINI_API_KEY` | `https://generativelanguage.googleapis.com/v1beta/openai` | `GEMINI_MODEL`, preset `gemini-3.8-flash` |
| DeepSeek | `deepseek` | `DEEPSEEK_API_KEY` | `https://api.deepseek.com/v1` | `DEEPSEEK_MODEL`, preset `deepseek-chat` |
| Claude | `claude` | `ANTHROPIC_API_KEY` | `https://api.anthropic.com/v1` | `CLAUDE_MODEL`, must be configured |
| Custom / 自定义 | `custom` | `LLM_API_KEY` | `LLM_BASE_URL`, must be configured | `LLM_MODEL`, must be configured |

`LLM_MODEL` and `LLM_BASE_URL`, if nonempty, override the selected preset. A generic `LLM_API_KEY` is a compatibility fallback; prefer provider-specific keys so switching services does not reuse the wrong credential. Changing API base URL changes where credentials and source text are sent. Use trusted endpoints. Requests do not follow redirects and require HTTPS, except loopback HTTP for local services.

OpenAI, Gemini, DeepSeek and custom use Chat Completions; Claude uses `/v1/messages` with `x-api-key`, `anthropic-version`, a top-level system message and a required output limit. The program asks for JSON in the prompt and applies the same source validation after either response format. Model support and access can change; update the model ID in your local settings if a service rejects it.

The ChatGPT option means the OpenAI developer API, not automating the ChatGPT website. Use your own developer API key.

中文：全局 `LLM_MODEL`、`LLM_BASE_URL` 有值时优先使用。各服务独立密钥更适合切换模型；自定义地址必须是你信任的服务，模型调用会向该地址发送密钥和来源文字。Claude 与其它服务的请求格式不同，程序已单独适配。未填写实际密钥时不会自动发布。

## Examples · 示例

OpenAI:

```dotenv
LLM_PROVIDER=openai
OPENAI_API_KEY=
OPENAI_MODEL=gpt-4.1-mini
LLM_MODEL=
LLM_BASE_URL=
```

Claude:

```dotenv
LLM_PROVIDER=claude
ANTHROPIC_API_KEY=
CLAUDE_MODEL=
LLM_MODEL=
LLM_BASE_URL=
```

Fill the empty key/model fields locally. Blank fields above are deliberate; no key is supplied by this repository.

## WeChat · 微信

Set `WECHAT_APP_ID`, `WECHAT_APP_SECRET` and optionally `WECHAT_AUTHOR`. The default template sets `AUTO_PUBLISH=true`; this enables publish-mode automatic cycles after credentials are configured. `AUTO_PUBLISH=false` stops publish-mode `run`/`watch`. Explicit `cli.py publish` and workbench publication are direct operator actions.

Verify material, draft and formal publication permissions in your account's backend, and configure the IP whitelist. `cli.py check` probes read-only endpoints, but success cannot prove permission to mutate drafts or submit publication. Calls that fail with unavailable permissions do not silently bypass WeChat. A timeout on a write leaves an uncertain state for manual verification rather than automatic retries.

中文：模板默认允许自动发布，但需要你账号真正具备官方接口权限。只读连接检查成功不等于有草稿写入或发布权限；正式发布失败会报告错误。此程序没有自动登录公众号网页、绕过权限或向粉丝群发的功能。

## Primary documentation · 官方文档

- [OpenAI Chat Completions](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)
- [OpenAI GPT-4.1 mini](https://developers.openai.com/api/docs/models/gpt-4.1-mini)
- [Gemini OpenAI compatibility](https://ai.google.dev/gemini-api/docs/openai)
- [DeepSeek Chat Completions](https://api-docs.deepseek.com/api/create-chat-completion/)
- [Claude API overview](https://platform.claude.com/docs/en/api/overview)
- [WeChat publication documentation](https://developers.weixin.qq.com/doc/offiaccount/Publish/Publish.html)
- [NCBI E-utilities](https://www.ncbi.nlm.nih.gov/books/NBK25501/)
- [arXiv API manual](https://info.arxiv.org/help/api/user-manual.html)

The WeChat documentation site may require opening it in a browser. Your account's backend and API errors determine actual permissions; this repository does not assert permissions for any specific account.
