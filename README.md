# WeChatPub · 英文科研来源自动微信公众号

[English](#english) · [中文](#中文) · [API setup / 接口设置](docs/API.md)

Search English scientific sources, generate evidence-linked Chinese commentary with AI, create article images, and publish through the WeChat Official Account API.

自动检索英文科研来源，AI 生成有来源证据的中文解读，制作文章包并通过微信公众号官方 API 发布。

## English

### Features and defaults

- Sources: **PubMed** research metadata/abstracts and permitted PMC full text; **arXiv** preprint metadata/abstracts. This is a scientific literature workflow, not a general news scraper.
- Topics: **brain**, **artificial intelligence**, **brain-computer interface / BCI**. Change both source queries and the column topic in the settings panel.
- Models: **ChatGPT / OpenAI**, **Gemini**, **DeepSeek**, **Claude**, and custom OpenAI-compatible endpoints. Claude uses its native Messages API.
- Default mode: **publish**, up to **3 papers per cycle**, a **30-day** lookback and **24-hour** interval. `draft` and `preview` are available.
- Automatic workflow: search → read sources → generate → validate quoted evidence → make cover/body images → upload → add draft → read back and verify → submit publication → query status.
- SQLite records prevent repeated publication of the same source within the same installation and account. A process lock prevents overlapping automatic cycles.
- If a mutation times out, the job stops in an uncertain state. It is not automatically resubmitted. Recovery uses a verified draft/publication ID.
- A local Streamlit workbench supports API configuration, source queries, preview, editing, export, draft upload and publication.

**No original API keys, WeChat credentials, run history, generated articles or copied paper figures are shipped.** Configure your own accounts. Merely opening the workbench does not publish anything; publication starts when you run a publish command or the automatic worker.

### Installation

Python **3.10+**. On Windows:

```powershell
git clone https://github.com/Y-123123/WeChatPub.git
cd WeChatPub
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
Copy-Item config.example.json config.json
.\.venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1
```

On macOS/Linux:

```bash
git clone https://github.com/Y-123123/WeChatPub.git
cd WeChatPub
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
cp config.example.json config.json
python -m streamlit run app.py --server.address 127.0.0.1
```

In **API and automation**, select a provider, set its model ID and key, and enter your WeChat AppID/AppSecret. Blank key fields keep the selected provider's saved key. Saving writes `.env` and `config.json`, both ignored by Git. For Claude, enter a model ID available to your API account. [API.md](docs/API.md) lists environment variables and official references.

The workbench is intended for a trusted local operator. It binds to loopback by default and has no multi-user authentication. If remotely deployed, put authentication and HTTPS in front of it. On Linux install a Chinese font or set `IMAGE_FONT` to a font file that supports Chinese characters.

### Full automation

Run one cycle:

```bash
python cli.py run
```

Run continuously (the first cycle starts immediately, then repeats every 24 hours by default):

```bash
python cli.py watch
```

Windows users may use `start-workbench.cmd` and `run-automatic.cmd`. The worker must remain running. To start it after reboot use Windows Task Scheduler or a Linux service. Alternatively schedule `python cli.py run` daily; avoid launching a second long-running worker each day. Use the virtual environment's Python and the project directory as the working directory.

The published defaults are in `config.example.json`. Copy it to `config.json` or save settings in the UI. Change `mode` to `preview` for local generation only, or `draft` for upload without formal publication. `AUTO_PUBLISH=false` blocks publish-mode automatic cycles. No keys means publish mode stops before searching or uploading.

Official publication requires your account to have the relevant material, draft and `freepublish/submit` API permissions and the correct IP whitelist. The program cannot grant those permissions. If the API rejects publication, inspect the error and choose draft/manual publication if needed. A `submitted` job is awaiting WeChat's result; only a queried `published` status confirms success. Publication is not the same operation as mass messaging followers; this program does not call the mass-send API.

### Commands

```bash
python cli.py check                         # read-only WeChat endpoint probes
python cli.py search --limit 5 --days 30     # PubMed search only
python cli.py generate --pmid 12345678       # generate a PubMed article bundle
python cli.py draft output/BUNDLE
python cli.py publish output/BUNDLE
python cli.py status output/BUNDLE
python cli.py recover output/BUNDLE --media-id VERIFIED_ID
python cli.py recover output/BUNDLE --publish-id VERIFIED_ID
python cli.py watch --interval-hours 12
python -m unittest discover -s tests -v
```

`run`/`watch` and the workbench use both configured sources; `search` and `generate --pmid` target PubMed. `recover` does not publish by itself. Keep `data/state.sqlite`: deleting it or running a separate clone removes that installation's deduplication history.

### Evidence and generated images

The writer checks that each commentary section cites a continuous passage from a source actually supplied to the model, rejects retracted/flagged PubMed articles, and escapes HTML. This checks provenance rather than proving every interpretation correct. arXiv records are labeled as preprints; peer-review and withdrawal status are not independently verified by this adapter.

The application generates simple original cover/source cards. PMC paper figures are downloaded only when the stored license and credit conditions allow automatic reuse; retain attribution. Arbitrary third-party figures and historical generated assets are not included. Optional custom schematics can be attached in the workbench; there is no paid image-generation API configured by default.

### Files and privacy

| File/directory | Purpose | Published in Git |
|---|---|---|
| `.env.example`, `config.example.json` | Credential-free defaults | Yes |
| `.env`, `config.json` | Your local credentials/settings | No |
| `data/` | Source searches, state database, logs | No |
| `output/` | Generated text, images and WeChat task files | No |
| `providers.py` | Provider request/response adapters | Yes |
| `sources.py` | PubMed/arXiv discovery | Yes |
| `tests/` | Offline/mocked checks | Yes |

Dependencies are installed separately; API usage is billed by your service providers. This repository is source code hosted on GitHub, not a deployed bot or GitHub Pages website.

## 中文

### 功能与默认配置

英文来源包括 **PubMed** 论文元数据与摘要、符合条件的 PMC 全文，以及 **arXiv** 预印本元数据与摘要。它适合科研公众号，不是通用新闻网站抓取器。

默认主题是 **brain（脑科学）**、**artificial intelligence（人工智能）** 和 **brain-computer interface（脑机接口）**。检索式和栏目主题可在界面修改。模型可选择 **ChatGPT/OpenAI、Gemini、DeepSeek、Claude** 或自定义兼容接口。

默认设置：**正式发布 `publish`、每轮最多 3 篇、最近 30 天、每 24 小时运行一轮**。自动流程为检索、读取来源、AI 中文解读、证据校验、封面与配图、上传草稿、回读核验、提交正式发布、查询状态。也可以切换为只预览或只上传草稿。

公开项目不包含原程序的密钥、公众号账号、生成文章、历史输出、数据库和原图。打开网页不会自行发布；运行自动任务或点击发布按钮后才会调用微信写入接口。

### 安装与接口配置

需要 Python **3.10 或更新版本**。Windows 安装命令见上方 English 的 PowerShell 示例：创建虚拟环境，安装 `requirements.txt`，复制 `.env.example` 和 `config.example.json`，然后启动 Streamlit。

在网页的 **“API 与自动发布设置”** 中：

1. 选择 AI 服务，填写模型 ID 和该服务的 API key。Claude 需要填写你账号可调用的模型 ID。
2. 填入公众号 AppID 与 AppSecret，并在公众号后台配置服务器公网 IP 白名单。
3. 设置栏目主题、PubMed/arXiv 检索式、来源、文章数、检索天数和任务间隔。
4. 默认选择 `publish`；如需人工编辑则选 `draft`，只本地生成选 `preview`。
5. 保存后启动自动任务。密钥输入框留空表示保留该服务已有的密钥。

设置保存在本地 `.env` 和 `config.json`，不会提交到 GitHub。各服务变量及文档链接见 [API 接口说明](docs/API.md)。ChatGPT 网站登录或订阅不能作为这里的 API key。

### 全自动运行

Windows 可双击 `run-automatic.cmd`，或使用虚拟环境执行：

```powershell
.\.venv\Scripts\python.exe cli.py watch
```

这会立即执行一轮，然后按设置的间隔循环。只执行一轮使用 `cli.py run`。工作台通过 `start-workbench.cmd` 启动。程序需要持续运行；开机启动可用 Windows 任务计划或 Linux 服务。也可每天定时执行一次 `cli.py run`。配置任务时使用项目的虚拟环境 Python，并将工作目录设为项目目录。

**实际能否正式发布取决于公众号权限。** 程序使用官方 `freepublish/submit`，不会绕过账号权限；没有权限时会报告错误，可切换草稿模式后在后台发布。`submitted` 仅代表提交成功，查询后显示 `published` 才代表发布成功。本程序不调用向粉丝群发消息的接口。

### 去重、异常与内容边界

- 同一安装目录与公众号通过 SQLite 记录防止同一来源重复发布；保留 `data/state.sqlite`。
- 自动任务有进程锁，避免多轮同时执行。已经提交或发布的文章不会在下一轮重新生成。
- 微信写入请求超时后结果可能未知，此时停止该任务，核对后台后用 `recover` 提供已确认的 ID，避免盲目重发。
- 正文中的证据摘录必须匹配模型实际读取的来源；撤稿或关注声明会阻止对应 PubMed 文献生成。
- arXiv 文章会注明预印本身份；本适配器不独立核验其同行评审、撤稿状态。
- 引用匹配不能保证全部解读正确。如需逐篇审阅，可选择草稿模式。
- 图片包括原创资料卡和许可符合条件的 PMC 原图，保留来源署名。额外示意图可手动导入，默认没有接入付费绘图 API。

### 验证与部署

测试命令是 `python -m unittest discover -s tests -v`，模型和微信请求使用模拟接口。公开版本未用真实密钥做收费模型调用或公众号发布测试。

工作台默认只监听本机，没有多用户认证；远程部署需配置登录保护与 HTTPS。Linux 用户请安装中文字体，或设置 `IMAGE_FONT` 为支持中文的字体路径。依赖和各家 API 费用由使用者自行配置承担。

GitHub 提供源代码和下载包；要自动发布，需要在你的电脑或服务器运行程序。
