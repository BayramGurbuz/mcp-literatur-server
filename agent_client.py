import asyncio
import os

from dotenv import load_dotenv
from google import genai
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

load_dotenv()

_client: genai.Client | None = None


def _get_client() -> genai.Client:
    """Tembel açılır: import zamanında değil, ilk `ask()` çağrısında.

    api.py bu modülü `from agent_client import ask` ile import ediyor;
    genai.Client() burada eager çalışsaydı, GEMINI_API_KEY olmayan bir
    ortamda (örn. CI, test suite) sadece import etmek bile çökerdi.
    """
    global _client
    if _client is None:
        _client = genai.Client()
    return _client


# StdioServerParameters, alt-process'e varsayılan olarak yalnızca güvenli bir
# allowlist (PATH, HOME vb.) geçiriyor — RAG_API_URL/INDEX_API_KEY bunda yok.
# paper_server.py'nin index_paper'ı bunlara ihtiyaç duyuyor; yerelde kendi
# load_dotenv()'i diskteki .env'i bulabildiği için bu fark edilmeyebilir, ama
# Docker/Render'da (.env imajda yok) subprocess bunlarsız kalır. Açıkça geçiyoruz.
server_params = StdioServerParameters(
    command="uv",
    args=["run", "paper_server.py"],
    env={
        "RAG_API_URL": os.environ.get("RAG_API_URL", ""),
        "INDEX_API_KEY": os.environ.get("INDEX_API_KEY", ""),
    },
)


def _extract_tool_result_text(result_obj) -> str:
    """MCP'nin CallToolResult'ından (ya da her neyse) düz bir metin çıkarır."""
    structured = getattr(result_obj, "structured_content", None)
    if isinstance(structured, dict) and "result" in structured:
        return str(structured["result"])
    content = getattr(result_obj, "content", None)
    if content:
        return "\n".join(getattr(part, "text", str(part)) for part in content)
    return str(result_obj)


def _parse_trace(history: list | None) -> list[dict]:
    """automatic_function_calling_history'den agent'ın tool çağrılarını çıkarır.

    SDK, otomatik function-calling döngüsü boyunca ürettiği tüm Content'leri
    (kullanıcı mesajı, model'in function_call'ları, tool'ların function_response'ları)
    response.automatic_function_calling_history'de bırakıyor — final metin bunun
    dışında (response.text). Bunu [{tool, args, result}, ...] haline getiriyoruz.
    """
    trace: list[dict] = []
    for content in history or []:
        for part in content.parts:
            if part.function_call:
                trace.append({"tool": part.function_call.name, "args": dict(part.function_call.args or {})})
            elif part.function_response and trace:
                result_obj = part.function_response.response.get("result")
                trace[-1]["result"] = _extract_tool_result_text(result_obj)
    return trace


async def ask_with_trace(question: str) -> tuple[str, list[dict]]:
    """ask()'ın aynısı, ama agent'ın hangi tool'ları hangi argümanlarla çağırdığını
    ve her birinden ne döndüğünü de (bkz. _parse_trace) döndürür — UI'da bir
    'agent ne yaptı' günlüğü göstermek için."""
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            # NOT: types.GenerateContentConfig(tools=[session]) yerine düz dict veriyoruz.
            # SDK, generate_content içinde config.model_copy(deep=True) çağırıyor ve bu,
            # ClientSession'ın içindeki canlı asyncio.Task'ı deep-copy'lemeye çalışıp
            # "TypeError: cannot pickle '_asyncio.Task' object" ile patlıyor (google-genai
            # 2.24.0, Python 3.11, Windows). Dict verildiğinde SDK farklı bir kod yoluna
            # girip bu deep-copy'yi atlıyor.
            response = await _get_client().aio.models.generate_content(
                model="gemini-flash-latest",
                contents=question,
                config={"tools": [session]},
            )
            return response.text, _parse_trace(response.automatic_function_calling_history)


async def ask(question: str) -> str:
    text, _trace = await ask_with_trace(question)
    return text


if __name__ == "__main__":
    answer, trace = asyncio.run(ask_with_trace("PubMed'de P300 speller ile ilgili son çalışmalardan 3 tanesinin başlığını ve PMID'sini söyle."))
    for step in trace:
        print(f"[Agent] {step['tool']}({step['args']}) -> {step.get('result')}")
    print(answer)
