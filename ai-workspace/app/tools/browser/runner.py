"""browser ツールの人間承認チャネル（CLI）。

nachtcode/runner.py の git push 確認ループと同型。executor が返した
needs_confirmation（ドメイン承認 / write承認）に対して、人間の入力を
受けてから同じ params ＋承認フラグで adapter を呼び直す。

  - ドメイン承認は3択: 今回だけ(y) / 恒久(p) / 拒否(n)。
    恒久(p)だけが add_domain_to_allowlist() を呼ぶ（人間チャネル専用）。
  - write承認は y/n。y なら confirmed=True ＋プレビュー時発行の
    ワンタイムトークンで呼び直す。submit_form は最終確認がもう1段続く。
  - 呼び直しの params は HUMAN_ONLY_PARAM_KEYS を除去してから、この
    チャネル自身が承認フラグを付け直す（LLM由来のフラグを引き継がない）。
"""

from __future__ import annotations

from app.tools.base import ToolRequest, ToolResult
from app.tools.browser.adapter import (
    HUMAN_ONLY_PARAM_KEYS,
    BrowserAdapter,
    add_domain_to_allowlist,
)

#: domain承認 → write承認 → submit_form最終確認 で最大3往復＋余白
_MAX_CONFIRM_ROUNDS = 4


def _clean(params: dict) -> dict:
    return {k: v for k, v in params.items() if k not in HUMAN_ONLY_PARAM_KEYS}


def handle_browser_confirmation(
    data: dict,
    task_text: str = "",
    adapter: BrowserAdapter | None = None,
    ask=input,
) -> ToolResult | None:
    """needs_confirmation を返した browser ステップの人間確認ループ。

    実行まで到達した場合はその ToolResult、人間が拒否した場合は None を返す。
    ask はテストで input を差し替えるための注入口。
    """
    adapter = adapter or BrowserAdapter()
    for _ in range(_MAX_CONFIRM_ROUNDS):
        kind = data.get("kind")
        action = str(data.get("action") or "")
        params = _clean(dict(data.get("params") or {}))

        if kind == "domain":
            print("=" * 60)
            print("browser ドメイン承認:")
            print(f"  ドメイン: {data.get('domain')}")
            print(f"  URL     : {data.get('url')}")
            try:
                answer = ask(
                    "アクセスを許可しますか? [y=今回だけ / p=恒久 / N=拒否]: "
                ).strip().lower()
            except EOFError:
                answer = ""
            if answer == "p":
                error = add_domain_to_allowlist(str(data.get("domain") or ""))
                if error:
                    print(error)
                    return None
                print(f"allowlist に恒久追記しました: {data.get('domain')}")
            elif answer != "y":
                print("アクセスを中止しました（実行していません）")
                return None
            params["domain_approved"] = True

        elif kind == "write":
            final = bool(data.get("final"))
            print("=" * 60)
            print("browser 最終確認（送信を伴います）:" if final
                  else f"browser 書き込み操作の確認: {action}")
            for line in str(data.get("preview") or "").splitlines():
                print(f"  {line}")
            prompt = ("本当に送信しますか? [y/N]: " if final
                      else f"{action} を実行しますか? [y/N]: ")
            try:
                answer = ask(prompt).strip().lower()
            except EOFError:
                answer = ""
            if answer != "y":
                print("中止しました（実行していません）")
                return None
            params["confirmed"] = True
            params["confirm_token"] = data.get("confirm_token")

        else:
            return None

        result = adapter.execute(ToolRequest(
            action=action, params=params, task_text=task_text
        ))
        if isinstance(result.data, dict) and result.data.get("needs_confirmation"):
            data = result.data
            continue
        return result
    return None
