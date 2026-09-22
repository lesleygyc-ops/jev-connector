# Jev 个人连接服务

这是一份待部署的 MCP 连接程序。它尚未部署到云端，也尚未安装成 ChatGPT 插件。
程序提供 `jev_evaluate`，支持分类（Choice）、评分（Score）和真假概率判断（Noul）。
它不会修改客服工单、执行设备操作或自动关单。

## 无需购买服务器的部署方式

采用 Prefect Horizon 托管。官方目前提供个人项目免费层，并支持 OAuth 认证；免费额度及限制以实际账号页面为准。Jev 自身的调用费用另计。

1. 注册自己的 GitHub 账号和 Horizon 账号：https://horizon.prefect.io/ 。
2. 在 GitHub 新建个人私有仓库，将本目录的 `server.py`、`requirements.txt` 等文件放到仓库根目录。不要上传密钥。
3. 在 Horizon 连接这个仓库，仅授权所需仓库。服务入口填写 `server.py:mcp`。
4. 开启 Horizon 的 Authentication，并确保允许连接的组织成员只有你本人或明确授权的人。
5. 在托管平台的环境变量/密钥配置中设置 `TYPESAFE_API_KEY`。先撤销曾在聊天中发送的旧密钥，重新生成一把，再直接填写到平台中。此步骤会把新密钥交给 Horizon 托管；程序用它向 TypeSafe API 发出请求。
6. 部署后复制平台提供的真实 MCP URL。不要把 TypeSafe API 地址填成 MCP 地址。
7. 在 ChatGPT 开启开发者模式，进入插件/应用的添加入口，填写上述 MCP URL，选择 OAuth 并完成登录授权。按钮名称以账号实际页面为准。
8. 安装后新开对话选择 Jev 插件，运行下方虚构测试。能看到 `jev_evaluate` 的工具调用、真实模型名和 token 用量后，才算完成端到端接入。

如果免费层要求升级、没有密钥配置入口或认证未生效，先停止部署并核实条件，不要为了完成接入关闭认证。此程序依赖托管平台提供远程认证；本机直接执行仅使用 stdio。

## 测试提示词

“调用 Jev 分析这条虚构工单：货柜有电但后台离线，客户重启后仍未恢复，未提供设备ID。判断故障现象类别、是否提供设备ID、重启是否未解决问题。展示原始判断、概率和用量，不推断硬件根因。”

## 访问与数据范围

- 数据路径：ChatGPT → 你的 Horizon 连接服务 → TypeSafe Jev → 返回结果。
- 仅发送用户指定的待分析文本和问题；不要上传无关聊天记录。第一次使用建议仅用虚构或脱敏工单。
- 密钥从托管环境读取，代码包不含任何真实密钥。服务不主动写入工单文件或打印工单、密钥；托管平台自身可能留存调用轨迹，应检查平台设置。
- 单次限制 20 个问题、40000 字符文本、100 KB 请求。默认不自动重试，避免重复计费。
- 分类置信度与真假概率均为模型估计，不能作为正确率或故障根因的保证。
- “持久接入”依赖有效账号、密钥、托管服务与插件授权，不代表承诺永久可用或免费。

## 本地验证

需要 Python 3.11 或更新版本，运行：

```bash
python -m venv .venv
# 激活环境后：
pip install -r requirements.txt
fastmcp inspect server.py:mcp
```

不填写密钥也可以检查工具定义；真实调用需要安全设置环境变量。包内未提供永久公开的无认证服务。

## 官方参考

- Horizon 部署和认证：https://gofastmcp.com/deployment/prefect-horizon
- Jev API：https://docs.typesafe.ai/introduction/quickstart
- ChatGPT 个人插件：https://developers.openai.com/plugins/quickstart

## 本次验证状态

已通过本地 MCP 工具发现、模拟接口往返、缺少密钥、非法评分参数和上游认证错误脱敏检查。验证使用虚构凭据和模拟响应，未将本程序部署到 Horizon，未完成 ChatGPT 插件端到端测试。

fastmcp==4.0.5
httpx==0.28.1
pydantic==2.13.5

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
