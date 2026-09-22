from fastapi import FastAPI
from pydantic import BaseModel

from agent_client import ask  # Faz 3'teki async fonksiyonun

app = FastAPI(title="MCP Literatür Agent")


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
