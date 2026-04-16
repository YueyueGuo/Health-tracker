from __future__ import annotations

from backend.services.analysis import AnalysisResult


def format_for_telegram(result: AnalysisResult, max_length: int = 4096) -> str:
    """Format an analysis result for Telegram (markdown)."""
    text = result.answer
    footer = f"\n\n_Model: {result.model}_"

    if len(text) + len(footer) > max_length:
        text = text[: max_length - len(footer) - 3] + "..."

    return text + footer


def format_sync_result(results: dict[str, int]) -> str:
    """Format sync results for display."""
    lines = ["**Sync complete:**"]
    for source, count in results.items():
        emoji = "+" if count > 0 else ""
        lines.append(f"- {source}: {emoji}{count} records")
    return "\n".join(lines)


def truncate(text: str, max_length: int = 2000) -> str:
    """Truncate text to fit within a message limit."""
    if len(text) <= max_length:
        return text
    return text[: max_length - 3] + "..."
