import os

from google import genai


MODEL_NAME = "gemini-3.5-flash-lite"


def fallback_summary(message: str) -> str:
    """Return a fallback when AI summarization is unavailable."""

    if not message or not message.strip():
        return "No report text available. Manual review required."

    return (
        "AI summarization unavailable. "
        "Review the original report manually."
    )


def summarize_report(message: str) -> dict:
    """
    Generate a concise disaster report summary using Gemini.

    If generation fails, return a provisional result
    that requires manual review.
    """

    if not message or not message.strip():
        return {
            "summary": fallback_summary(message),
            "is_provisional": True,
            "requires_manual_review": True,
        }

    api_key = os.getenv("GEMINI_API_KEY")

    if not api_key:
        return {
            "summary": fallback_summary(message),
            "is_provisional": True,
            "requires_manual_review": True,
        }

    try:
        client = genai.Client(api_key=api_key)

        prompt = f"""
You are summarizing disaster reports for RESQ Kerala,
an emergency response coordination system.

Summarize the following disaster report in 2-3 concise sentences.

Instructions:
- Preserve locations and important numbers.
- Preserve the number of people affected, if stated.
- Include requests for rescue, food, water, medical assistance,
  shelter, or other essential help.
- Do not invent facts or infer unstated information.
- Do not omit critical information about people in danger.
- Do not guess when information is unclear.
- Return only the summary.

Original disaster report:
<report>
{message}
</report>
"""

        interaction = client.interactions.create(
            model=MODEL_NAME,
            input=prompt,
        )

        summary = (interaction.output_text or "").strip()

        if not summary:
            raise ValueError("Gemini returned an empty summary.")

        return {
            "summary": summary,
            "is_provisional": False,
            "requires_manual_review": False,
        }

    except Exception as error:
        print(f"Gemini summarization error: {error}")

        return {
            "summary": fallback_summary(message),
            "is_provisional": True,
            "requires_manual_review": True,
        }