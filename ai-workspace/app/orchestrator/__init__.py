"""orchestrator層: タスク受理・分類・モデル選択・ツール呼び出し制御.

core は llm層に依存し、llm層（router）は classifier の TaskKind に依存する。
ここで core を即時 import すると循環importになるため、遅延解決にしている。
"""

from app.orchestrator.classifier import TaskKind, classify_task

__all__ = ["TaskKind", "classify_task", "Orchestrator", "TaskOutcome"]


def __getattr__(name: str):
    if name in ("Orchestrator", "TaskOutcome"):
        from app.orchestrator import core
        return getattr(core, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
