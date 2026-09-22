# MCP Literatür Agent

![CI](https://github.com/BayramGurbuz/mcp-literatur-server/actions/workflows/ci.yml/badge.svg)

PubMed'de arama yapan, tek bir makalenin abstract'ını getiren ve (yapılandırılmışsa) sonuçları [rag-literature-assistant](https://github.com/BayramGurbuz/rag-literature-assistant)'ın RAG koleksiyonuna indeksleyebilen bir [MCP](https://modelcontextprotocol.io/) server'ı, buna bağlanan bir Gemini agent'ı ve bu agent'ı saran bir HTTP API.

**Canlı:** https://mcp-literatur-server.onrender.com/docs (Render ücretsiz katman — ilk istek, cold start + alt-process başlatma nedeniyle 20-30 saniye sürebilir)

- **Agent modeli:** `gemini-flash-latest`
- **Transport:** stdio (agent, `paper_server.py`'ı alt-process olarak başlatıp JSON-RPC ile konuşur)

## Kurulum

```bash
uv sync
```

`.env` dosyası oluştur:

```
GEMINI_API_KEY=...
```

## Kullanım

### Doğrudan agent (terminal)

```bash
uv run python agent_client.py
```

### HTTP API

```bash
uv run uvicorn api:app --port 8000
```

> **Windows'ta not:** `uv run fastapi dev api.py` (hot-reload modu) bu projede `/ask`'ı sessizce 500'letiyor — reload mekanizması, MCP'nin alt-process başlatmak için ihtiyaç duyduğu asyncio subprocess desteğini bozuyor. Yerelde geliştirirken reload'suz `uvicorn api:app` kullan; Docker/Render zaten reload'suz çalışıyor, orada sorun yok.

`http://127.0.0.1:8000/docs` adresinde Swagger arayüzü açılır.

| Endpoint | Açıklama |
|---|---|
| `POST /ask` | `{"question": "..."}` gönder, `{"answer": "..."}` al |
| `GET /health` | Servisin ayakta olup olmadığını kontrol eder |

```bash
curl -X POST http://127.0.0.1:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "PubMed de SSVEP ile ilgili 2 makale bul, baslik ve PMID soyle."}'
```

### Docker

```bash
docker build -t mcp-api .
docker run -p 8000:8000 --env-file .env mcp-api
```

`agent_client.py`, `paper_server.py`'ı `uv run paper_server.py` ile alt-process olarak başlattığı için `uv`'nin runtime image'ında da bulunması gerekir (sadece build aşamasında değil) — Dockerfile'ın final aşaması bunun için `uv` binary'sini ayrıca kopyalar.

**`GEMINI_API_KEY`'in alt-process'e geçişi:** MCP'nin `StdioServerParameters`'ı, alt-process'e varsayılan olarak yalnızca güvenli bir allowlist (`PATH`, `HOME` vb.) geçirir — rastgele ortam değişkenlerini (örn. `GEMINI_API_KEY`) otomatik geçirmez. `agent_client.py` bunu `env={"GEMINI_API_KEY": ...}` ile açıkça iletir; aksi halde `paper_server.py` alt-process'i Docker'da (yerelde `.env` dosyasından tembelce yükleyebildiği gibi bir şansı olmadan) key'siz kalıp çökerdi.

## Deploy (Render)

`GEMINI_API_KEY` env var olarak eklenir. **`RAG_CHROMA_DB_PATH` bilerek eklenmez** — bu, `index_paper` tool'unun production'da devre dışı kalmasını sağlayan bilinçli bir tercih (aşağıya bak).

**`index_paper` production'da neden kapalı:** Bu araç, [rag-literature-assistant](https://github.com/BayramGurbuz/rag-literature-assistant)'ın Chroma koleksiyonuna doğrudan yazar. İki servis Render'da ayrı container'lar/ayrı disklerde çalıştığı için bu artık mümkün değil (paylaşılan disk yok). `RAG_CHROMA_DB_PATH` tanımsızsa `index_paper` çökmek yerine "İndeksleme bu ortamda yapılandırılmamış" mesajıyla nazikçe kapanır — servisin tamamı bu yüzden etkilenmez.

Detaylar için [FAZ4_RAPOR.md](FAZ4_RAPOR.md)'a bak.

## Test

```bash
uv run pytest -v
```

`tests/test_api.py`, gerçek bir Gemini/MCP çağrısı yapmadan `api.ask`'ı `unittest.mock.AsyncMock` ile sahteler (`ask` async olduğu için).

## Mimari

```
Gemini agent (agent_client.py, async)
        │  client.aio.models.generate_content(config={"tools": [session]})
        ▼
 ClientSession  ──stdio (JSON-RPC)──►  paper_server.py (alt-process, "uv run" ile başlar)
        │                                     │
        │  1) list_tools()                    ├─ ping(message)
        │  2) call_tool(isim, argümanlar)      ├─ search_papers(query, max_results)  ──► PubMed esearch+esummary
        │                                      ├─ get_abstract(pmid)                 ──► PubMed efetch (XML)
        │                                      └─ index_paper(pmid)                  ──► RAG_CHROMA_DB_PATH tanımlıysa
        ▼                                                                                  Chroma upsert, yoksa nazik mesaj
   response.text
```

Faz 3'ün orijinal tasarım kararları için [FAZ3_RAPOR.md](FAZ3_RAPOR.md)'a; API/Docker/CI/Render'a geçiş süreci ve karşılaşılan gerçek sorunlar için [FAZ4_RAPOR.md](FAZ4_RAPOR.md)'a bak.
