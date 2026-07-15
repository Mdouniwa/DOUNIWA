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
    )

    print("=" * 60)
    print(f"タスク種別 : {outcome.task_kind}")
    print(f"使用モデル : {outcome.model_name}（{outcome.route_reason}）")
    if outcome.tool_name:
        print(f"使用ツール : {outcome.tool_name}")
        print(f"ツール成否 : {'成功' if outcome.tool_ok else '失敗'}")
        print(f"ツール結果 : {outcome.tool_output}")
    if outcome.stubbed:
        print("注記       : stub 応答を含みます（実接続なし）")
    print(f"記録ID     : {outcome.record_id}")
    print("=" * 60)
    print(outcome.llm_output)
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
    run.set_defaults(func=_cmd_run)

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
