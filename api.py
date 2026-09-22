import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel

from agent_client import ask_with_trace

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

STATIC_DIR = Path(__file__).resolve().parent / "static"


@app.get("/", include_in_schema=False)
def home() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


class AskRequest(BaseModel):
    question: str


class TraceStep(BaseModel):
    tool: str
    args: dict
    result: str | None = None


class AskResponse(BaseModel):
    answer: str
    trace: list[TraceStep] = []


@app.post("/ask", response_model=AskResponse)
async def ask_endpoint(request: AskRequest) -> AskResponse:
    answer, trace = await ask_with_trace(request.question)
    return AskResponse(answer=answer, trace=trace)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
