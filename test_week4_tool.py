
import asyncio
import inspect

from agents.tool import ToolContext
from backend.ai.week4_orchestrator import (
    Week4Context,
    tool_1_extract_location,
)


async def main():
    context = Week4Context(
        db=None,
        incident=type("Incident", (), {"id": 6})(),
        original_text="Please help. My house is near Aluva.",
        reported_location="Aluva",
    )

    tool_context = ToolContext(
        context=context,
        tool_name="tool_1_extract_location",
        tool_call_id="test-call-1",
        tool_arguments="{}",
    )

    result = tool_1_extract_location.on_invoke_tool(
        tool_context,
        "{}",
    )

    if inspect.isawaitable(result):
        result = await result

    print("Tool result:", result)
    print("Saved result:", context.results)


if __name__ == "__main__":
    asyncio.run(main())
