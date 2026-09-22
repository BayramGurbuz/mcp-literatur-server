# MCP Literatür Agent

![CI](https://github.com/BayramGurbuz/mcp-literatur-server/actions/workflows/ci.yml/badge.svg)

PubMed'de arama yapan, tek bir makalenin abstract'ını getiren ve (yapılandırılmışsa) sonuçları [rag-literature-assistant](https://github.com/BayramGurbuz/rag-literature-assistant)'ın RAG koleksiyonuna **HTTP üzerinden** indeksleyebilen bir [MCP](https://modelcontextprotocol.io/) server'ı, buna bağlanan bir Gemini agent'ı ve bu agent'ı saran bir HTTP API.

**Canlı:** https://mcp-literatur-server.onrender.com/ — sadece final cevabı değil, agent'ın hangi tool'u hangi argümanla çağırdığını da gösteren bir arayüz (ham API için [/docs](https://mcp-literatur-server.onrender.com/docs)). Render ücretsiz katman — ilk istek, cold start + alt-process başlatma nedeniyle 20-30 saniye sürebilir.

- **Agent modeli:** `gemini-2.5-flash`
- **Transport:** stdio (agent, `paper_server.py`'ı alt-process olarak başlatıp JSON-RPC ile konuşur)

## Kurulum

```bash
uv sync
```

`.env` dosyası oluştur:

```
GEMINI_API_KEY=...
RAG_API_URL=http://127.0.0.1:8010   # index_paper için, opsiyonel: rag-literature-assistant'ın adresi
INDEX_API_KEY=...                    # opsiyonel, rag-literature-assistant'ta INDEX_API_KEY ayarlıysa aynısı buraya
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

`http://127.0.0.1:8000/` adresinde agent'ın tool-çağırma günlüğünü gösteren özel bir arayüz açılır; `/docs`'ta ham API için Swagger.

| Endpoint | Açıklama |
|---|---|
| `GET /` | Özel HTML/JS arayüz — soru sor, agent'ın hangi tool'u hangi argümanla çağırdığını ve sonucunu adım adım gör, sonra final cevabı gör |
| `POST /ask` | `{"question": "..."}` gönder, `{"answer": "...", "trace": [{"tool", "args", "result"}, ...]}` al |
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

**`RAG_API_URL`/`INDEX_API_KEY`'in alt-process'e geçişi:** MCP'nin `StdioServerParameters`'ı, alt-process'e varsayılan olarak yalnızca güvenli bir allowlist (`PATH`, `HOME` vb.) geçirir — rastgele ortam değişkenlerini otomatik geçirmez. `agent_client.py` bunları `env={...}` ile açıkça iletir; aksi halde `paper_server.py` alt-process'i Docker'da (yerelde `.env` dosyasından tembelce yükleyebildiği gibi bir şansı olmadan) bunlarsız kalıp `index_paper`'ı hep "yapılandırılmamış" derdi.

## Deploy (Render)

`GEMINI_API_KEY` eklenir; `index_paper`'ın çalışması için ayrıca `RAG_API_URL=https://rag-literature-assistant.onrender.com` ve (rag-literature-assistant'ta `INDEX_API_KEY` ayarlıysa) aynı `INDEX_API_KEY` eklenir.

**`index_paper` nasıl çalışıyor:** Bu araç artık Chroma'ya doğrudan yazmıyor — iki servis ayrı container'lar/disklerde çalıştığı için bu mümkün değil. Bunun yerine `rag-literature-assistant`'ın `POST /index` endpoint'ini HTTP üzerinden çağırıyor; o servis PubMed'den çekip kendi koleksiyonuna ekliyor. `RAG_API_URL` tanımsızsa `index_paper` çökmek yerine "yapılandırılmamış" mesajıyla nazikçe kapanır.

**Canlıda doğrulandı:** mcp-literatur-server'a bir PMID indekslettirilip hemen ardından rag-literature-assistant'a o makalenin konusuyla ilgili bir soru sorularak, gerçekten aranabilir hale geldiği kanıtlandı.

**Maliyet:** Agent modeli, gerçek bir Gemini ön ödeme kredisi tükenmesi (RESOURCE_EXHAUSTED, HTTP 402) yaşanınca `gemini-flash-latest`'tan daha ucuz `gemini-2.5-flash`'a düşürüldü.

Detaylar için [FAZ4_RAPOR.md](FAZ4_RAPOR.md)'a bak.

## Test

```bash
uv run pytest -v   # 6 test
```

`tests/test_api.py`, gerçek bir Gemini/MCP çağrısı yapmadan `api.ask_with_trace`'i `unittest.mock.AsyncMock` ile sahteler (`ask_with_trace` async olduğu için).

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
        │                                      └─ index_paper(pmid)                  ──► RAG_API_URL tanımlıysa
        ▼                                                                                  POST {RAG_API_URL}/index,
   response.text                                                                            yoksa nazik mesaj
```

`index_paper`, rag-literature-assistant'ın `/index`'ini çağırıyor — o servis kendi `fetch_papers`/`index_paper` fonksiyonlarıyla PubMed'den çekip parçalayıp embed'liyor. Bu repo artık kendi başına ne Chroma'ya ne embedding'e dokunuyor.

**Trace nereden geliyor:** `google-genai`'nin otomatik function-calling döngüsü, attığı her tool çağrısını ve aldığı her sonucu `response.automatic_function_calling_history`'de bırakıyor (final metnin dışında, `response.text`'te). `agent_client._parse_trace` bunu `[{"tool", "args", "result"}, ...]`'a çeviriyor — `GET /` bunu adım adım gösteriyor.

Faz 3'ün orijinal tasarım kararları için [FAZ3_RAPOR.md](FAZ3_RAPOR.md)'a; API/Docker/CI/Render'a geçiş süreci ve karşılaşılan gerçek sorunlar için [FAZ4_RAPOR.md](FAZ4_RAPOR.md)'a bak.
