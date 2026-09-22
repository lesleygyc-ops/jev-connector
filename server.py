"""Personal Jev MCP bridge. Deploy behind Horizon's authenticated gateway."""

import json
import os
from typing import Annotated, Any, Literal

import httpx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import BaseModel, ConfigDict, Field


class ChoiceQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["choice"]
    instructions: str = Field(min_length=1, max_length=4000)
    criteria: dict[str, str] = Field(min_length=2, max_length=255)


class ScoreQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["score"]
    instructions: str = Field(min_length=1, max_length=4000)
    criteria: list[str] = Field(min_length=2, max_length=10)


class NoulQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["noul"]
    instructions: str = Field(min_length=1, max_length=4000)


Question = Annotated[
    ChoiceQuestion | ScoreQuestion | NoulQuestion, Field(discriminator="type")
]

mcp = FastMCP(
    "Jev Connector",
    instructions=(
        "Use Jev only when the user requests Jev classification, scoring, or "
        "probability judgments. Send only the text relevant to that request. "
        "Never send API keys or unrelated chat history. Returned confidence is "
        "a model estimate, not a guarantee. Do not claim permanent availability "
        "from a single successful call. This tool cannot modify tickets or "
        "execute refunds, replacements, or device actions."
    ),
)


@mcp.tool(annotations={
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": False,
    "openWorldHint": True,
})
async def jev_evaluate(
    state: Annotated[str, Field(min_length=1, max_length=40000)],
    questions: Annotated[dict[str, Question], Field(min_length=1, max_length=20)],
) -> dict[str, Any]:
    """Send user-authorized text to TypeSafe Jev for structured decisions.

    This transmits the supplied state and questions to TypeSafe AI and uses
    the owner's paid or free API quota. Choice selects from named criteria;
    Score rates ordered criteria; Noul estimates whether a statement is true.
    For support tickets, classify reported symptoms rather than inventing
    root causes. Include an unclear category when classification is uncertain.
    Returns Jev's model, answers, and token usage. Does not generate prose.
    """
    key = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if not key:
        raise ToolError("Jev key is not configured. Set TYPESAFE_API_KEY in hosting secrets.")

    payload = {
        "model": "jev-latest",
        "state": state,
        "questions": {name: question.model_dump() for name, question in questions.items()},
    }
    encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    if len(encoded) > 100000:
        raise ToolError("Request exceeds 100 KB. Split the input into smaller requests.")
    try:
        async with httpx.AsyncClient(timeout=45.0, follow_redirects=False) as client:
            response = await client.post(
                "https://api.typesafe.ai/v1/systemone",
                content=encoded,
                headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
            )
    except httpx.TimeoutException:
        raise ToolError("Jev timed out. No automatic retry was made; usage may have occurred.") from None
    except httpx.RequestError:
        raise ToolError("Cannot reach Jev. No automatic retry was made.") from None

    # Do not return raw upstream errors, headers, or request objects: they may
    # contain request content or sensitive details.
    if response.status_code in (401, 403):
        raise ToolError("Jev rejected authentication or access. Check the key and account.")
    if response.status_code == 429:
        raise ToolError("Jev rate or quota limit reached. No automatic retry was made.")
    if response.status_code != 200:
        raise ToolError(f"Jev returned HTTP {response.status_code}. No automatic retry was made.")
    try:
        result = response.json()
    except ValueError:
        raise ToolError("Jev returned invalid JSON.") from None
    if not isinstance(result, dict) or not isinstance(result.get("answers"), dict):
        raise ToolError("Jev response did not contain structured answers.")
    if set(result["answers"]) != set(questions):
        raise ToolError("Jev returned an unexpected set of question answers.")
    return {
        "provider": "TypeSafe AI",
        "model": result.get("model"),
        "answers": result["answers"],
        "usage": result.get("usage"),
    }


if __name__ == "__main__":
    # Local stdio testing only. Horizon imports server.py:mcp and provides
    # the authenticated HTTPS endpoint. Do not expose an unauthenticated port.
    mcp.run()
