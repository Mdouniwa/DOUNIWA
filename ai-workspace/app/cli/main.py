"""CLI エントリーポイント。

使い方:
  ai-workspace run "このリポジトリのREADMEを読んで改善点を出して"
  ai-workspace run --model llama-70b "設計レビューして"
  ai-workspace run --quality "重要な仕様の矛盾を洗い出して"
  ai-workspace models

標準ライブラリの argparse のみ使用（依存を増やさない）。
サブコマンドが増えたら app/cli/ 配下にモジュールを分割する。
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

from dotenv import load_dotenv


def _cmd_run(args: argparse.Namespace) -> int:
    # import を遅延させ、`ai-workspace models` 等が軽く動くようにする
    from app.orchestrator.core import Orchestrator

    tool_params = {}
    if args.param:
        for item in args.param:
            if "=" not in item:
                print(f"error: --param は key=value 形式で指定してください: {item}",
                      file=sys.stderr)
                return 2
            key, value = item.split("=", 1)
            tool_params[key] = value

    orchestrator = Orchestrator()
    outcome = orchestrator.run(
        args.task,
        explicit_model=args.model,
        quality_first=args.quality,
        tool_params=tool_params,
        session_id=args.session,
    )

    print("=" * 60)
    print(f"タスク種別 : {outcome.task_kind}")
    print(f"使用モデル : {outcome.model_name}（{outcome.route_reason}）")
    print(f"実行計画   : {outcome.plan_source}（{len(outcome.steps)}ステップ）"
          + (f" — {outcome.plan_note}" if outcome.plan_note else ""))
    if outcome.plan_rejected:
        print("注記       : 安全ガードにより計画を拒否（何も実行していません）")
    total = len(outcome.steps)
    for r in outcome.steps:
        print(f"Step {r.index}/{total}: {r.label} → {r.status}")
        if not r.skipped and r.output:
            summary = r.output[:160].replace("\n", " ")
            print(f"          {summary}")
    if outcome.stubbed:
        print("注記       : stub 応答を含みます（実接続なし）")
    print(f"記録ID     : {outcome.record_id}")
    print("=" * 60)
    print(outcome.llm_output)
    return 0


def _cmd_noircode(args: argparse.Namespace) -> int:
    from app.tools.noircode.runner import run_noircode_task

    return run_noircode_task(
        args.dir, args.task, assume_yes=args.yes, model_name=args.model
    )


def _cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    uvicorn.run("app.server.main:app", host=args.host, port=args.port)
    return 0


def _cmd_models(_args: argparse.Namespace) -> int:
    from app.llm.models import DEFAULT_MODEL, list_models

    rows = []
    for spec in list_models():
        rows.append({
            "name": spec.name,
            "tier": spec.tier.value,
            "provider": spec.provider.value,
            "served_model_name": spec.served_model_name,
            "endpoint_configured": spec.resolve_endpoint() is not None,
            "default": spec.name == DEFAULT_MODEL,
            "description": spec.description,
        })
    print(json.dumps(rows, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ai-workspace",
        description="ローカルLLM中心の個人用AIワークスペース（PoC）",
    )
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="詳細ログ（ルーティング判断等）を表示")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="自然言語タスクを実行する")
    run.add_argument("task", help="自然言語のタスク指示")
    run.add_argument("--model", default=None,
                     help="使用モデルを明示指定（例: qwen-35b, llama-70b, cloud-claude）")
    run.add_argument("--quality", action="store_true",
                     help="速度より品質を優先（70B級を使用）")
    run.add_argument("--param", action="append", metavar="KEY=VALUE",
                     help="ツールに渡す追加パラメータ（例: --param repo=owner/name）")
    run.add_argument("--session", default=None, metavar="SESSION_ID",
                     help="会話ID。同一IDのタスクだけが「さっきの結果」の参照対象になる")
    run.set_defaults(func=_cmd_run)

    noir = sub.add_parser(
        "noircode",
        help="Nacht Code: 指定ディレクトリ内のコードを読み書きするエージェント",
    )
    noir.add_argument("task", help="コーディングタスクの指示")
    noir.add_argument("--dir", required=True,
                      help="対象プロジェクトディレクトリ（絶対パス・必須）")
    noir.add_argument("--yes", action="store_true",
                      help="git管理外ディレクトリでも実行する（バックアップ確認済みの明示）")
    noir.add_argument("--model", default=None, help="使用モデルを明示指定")
    noir.set_defaults(func=_cmd_noircode)

    serve = sub.add_parser("serve", help="Web UI（kuro·console）を起動する")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=7860)
    serve.set_defaults(func=_cmd_serve)

    models = sub.add_parser("models", help="登録済みモデル一覧を表示する")
    models.set_defaults(func=_cmd_models)

    return parser


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
