import asyncio
import os

from dotenv import load_dotenv
from google import genai
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

load_dotenv()
client = genai.Client()

# StdioServerParameters, alt-process'e varsayılan olarak yalnızca güvenli bir
# allowlist (PATH, HOME vb.) geçiriyor — GEMINI_API_KEY bunda yok. paper_server.py
# kendi genai.Client()'ını kurarken bu key'e ihtiyaç duyuyor; production'da (Docker/
# Render) .env dosyası imajda olmadığı için server'ın kendi load_dotenv()'i de onu
# bulamıyor. Açıkça geçiyoruz.
server_params = StdioServerParameters(
    command="uv",
    args=["run", "paper_server.py"],
    env={"GEMINI_API_KEY": os.environ.get("GEMINI_API_KEY", "")},
)


async def ask(question: str) -> str:
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            # NOT: types.GenerateContentConfig(tools=[session]) yerine düz dict veriyoruz.
            # SDK, generate_content içinde config.model_copy(deep=True) çağırıyor ve bu,
            # ClientSession'ın içindeki canlı asyncio.Task'ı deep-copy'lemeye çalışıp
            # "TypeError: cannot pickle '_asyncio.Task' object" ile patlıyor (google-genai
            # 2.24.0, Python 3.11, Windows). Dict verildiğinde SDK farklı bir kod yoluna
            # girip bu deep-copy'yi atlıyor.
            response = await client.aio.models.generate_content(
                model="gemini-flash-latest",
                contents=question,
                config={"tools": [session]},
            )
            return response.text


if __name__ == "__main__":
    answer = asyncio.run(ask("PubMed'de P300 speller ile ilgili son çalışmalardan 3 tanesinin başlığını ve PMID'sini söyle."))
    print(answer)
