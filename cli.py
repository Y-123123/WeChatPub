import argparse
import json
import sys
import time

from pipeline import ROOT, build, export, load_env, recover, run, send, status
from pubmed import DEFAULT_QUERY, PubMed
from wechat import WeChat
from settings import load_config


def main():
    load_env()
    parser = argparse.ArgumentParser(description="PubMed/arXiv → AI 中文解读 → 微信文章包与自动发布")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check")
    search = commands.add_parser("search")
    search.add_argument("--query", default=DEFAULT_QUERY)
    search.add_argument("--limit", type=int, default=5)
    search.add_argument("--days", type=int, default=365)
    generate = commands.add_parser("generate")
    generate.add_argument("--pmid", required=True)
    generate.add_argument("--topic", default="脑科学、人工智能与脑机接口")
    for name in ("export", "draft", "publish", "status"):
        p = commands.add_parser(name)
        p.add_argument("folder")
        if name == "draft":
            p.add_argument("--update-existing", action="store_true", help="更新同 PMID 的现有草稿")
    p = commands.add_parser("recover")
    p.add_argument("folder")
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--media-id")
    group.add_argument("--publish-id")
    for name in ("run", "watch"):
        p = commands.add_parser(name)
        p.add_argument("--config", default=str(ROOT / "config.json"))
        if name == "watch":
            p.add_argument("--interval-hours", type=float, default=None)
    args = parser.parse_args()
    if args.command == "check":
        result = WeChat().check()
    elif args.command == "search":
        result = PubMed().search(args.query, args.limit, args.days)
    elif args.command == "generate":
        records = PubMed().fetch([args.pmid])
        if not records:
            raise ValueError("未找到此 PMID。")
        result = {"folder": str(build(records[0], args.topic))}
    elif args.command == "export":
        export(args.folder)
        result = {"exported": args.folder}
    elif args.command in ("draft", "publish"):
        result = send(args.folder, publish=args.command == "publish", replace_existing=getattr(args, "update_existing", False))
    elif args.command == "status":
        result = status(args.folder)
    elif args.command == "recover":
        result = recover(args.folder, args.media_id, args.publish_id)
    else:
        if args.command == "watch" and args.interval_hours is not None and args.interval_hours < 1:
            raise ValueError("定期检索间隔至少 1 小时。")
        while True:
            config = load_config(args.config)
            try:
                result = run(config)
            except (ValueError, RuntimeError, OSError) as error:
                if args.command == "run":
                    raise
                result = {"error": str(error), "retry": "next cycle; ambiguous submissions are never resent"}
            if args.command == "run":
                break
            print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
            interval = args.interval_hours if args.interval_hours is not None else float(config.get("interval_hours", 24))
            if interval < 1:
                raise ValueError("Automatic interval must be at least one hour.")
            time.sleep(interval * 3600)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("已停止。", file=sys.stderr)
    except Exception as error:
        # Do not print requests exceptions, response bodies, or full tracebacks with API URLs.
        if isinstance(error, (ValueError, RuntimeError, OSError)):
            print("错误：" + str(error), file=sys.stderr)
        else:
            print("错误：" + type(error).__name__ + "；请检查配置或响应格式。", file=sys.stderr)
        sys.exit(1)
