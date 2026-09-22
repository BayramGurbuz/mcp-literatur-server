import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from pydantic import BaseModel

from agent_client import ask  # Faz 3'teki async fonksiyonun

load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # TestClient(app) 'with' bloğu olmadan lifespan'ı hiç tetiklemez, bu yüzden
    # bu kontrol testleri (ve import'u) key'siz ortamlarda (CI) bozmuyor, ama
    # gerçek deploy'da container hemen (ilk /ask'ta değil) çöküyor.
    if not os.getenv("GEMINI_API_KEY"):
        raise RuntimeError("GEMINI_API_KEY ortam değişkeni ayarlanmamış.")
    yield


app = FastAPI(title="MCP Literatür Agent", lifespan=lifespan)


class AskRequest(BaseModel):
    question: str


class AskResponse(BaseModel):
    answer: str


@app.post("/ask", response_model=AskResponse)
async def ask_endpoint(request: AskRequest) -> AskResponse:
    answer = await ask(request.question)
    return AskResponse(answer=answer)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
