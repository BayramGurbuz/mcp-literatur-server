# Faz 4 Raporu — MCP Agent'ı Üretime Alma

**Proje:** Faz 3'teki MCP agent'ını (`agent_client.py` + `paper_server.py`) FastAPI ile HTTP API'ye sarma, Docker ile konteynerleştirme, GitHub Actions ile CI kurma ve Render'a canlı deploy etme.
**Klasör:** `mcp-literatur-server/` (kendi başına bir repo — bkz. [rag-literature-assistant/FAZ4_RAPOR.md](https://github.com/BayramGurbuz/rag-literature-assistant/blob/main/FAZ4_RAPOR.md) Bölüm 0)
**Canlı URL:** https://mcp-literatur-server.onrender.com (`/docs`, `/health`, `/ask`)
**CI:** GitHub Actions, her push/PR'da `pytest`

---

## 1. Özet

rag-literature-assistant için Faz 4'te kurulan desen (FastAPI → Docker → CI → Render) burada da tekrarlandı, ama bu proje **asenkron bir agent'ı ve MCP üzerinden başka bir alt-process'i** sardığı için, doğrudan kopyalanamayan **4 gerçek sorun** çıktı — hepsi gerçek `docker build`/`docker run` ve canlı Render isteğiyle bulunup doğrulandı:

1. `StdioServerParameters`'ın alt-process'e `GEMINI_API_KEY`'i hiç geçirmemesi (env allowlist).
2. Dockerfile şablonunun `uv`'yi yalnızca build aşamasına koyup runtime'a taşımaması.
3. `agent_client.py` **ve** `agent_basics.py`'de modül-seviyesi `genai.Client()` çağrılarının CI'da (API key yok) import anında çökmesi.
4. Windows'ta `fastapi dev` (reload modu) altında `/ask`'ın sessizce 500 vermesi (reload'un asyncio subprocess desteğini bozması).

---

## 2. Alıştırma 6 — FastAPI ile sarma

`api.py` yazıldı: `POST /ask` (async, `agent_client.ask()`'ı doğrudan `await`'liyor), `GET /health`.

**Bulunan sorun (yerel test, Windows):** `uv run fastapi dev api.py` ile `/ask` her zaman **sessizce** 500 veriyordu — `docker logs`/log dosyasında hiçbir traceback bile görünmüyordu. `ask()`'ı doğrudan Python'dan çağırınca (reload'suz) sorunsuz çalıştığı görüldü. Reload'suz `uv run uvicorn api:app` ile de sorunsuz çalıştı (7sn, gerçek PubMed sonuçlarıyla). Kök sebep kesin olarak izole edilmedi ama gözlem tekrarlanabilir: uvicorn'un Windows'taki `--reload` mekanizması, MCP'nin `stdio_client`'ının alt-process başlatmak için ihtiyaç duyduğu event loop kurulumunu bozuyor. **Pratik sonuç:** bu projede yerel geliştirme için `fastapi dev` yerine düz `uvicorn api:app` kullanılmalı; Docker/Render zaten reload'suz çalıştığı için orada sorun yok (ve gerçekten yok — Bölüm 3'te doğrulandı).

---

## 3. Alıştırma 7 — Dockerize, CI, Deploy

### Dockerize

Dockerfile, rag-literature-assistant'takiyle aynı çok-aşamalı şablondan (Python 3.11-slim, `.python-version` ile uyumlu) başladı, **bir farkla:** `agent_client.py`'nin `StdioServerParameters(command="uv", args=["run", "paper_server.py"])` satırı, `uv`'nin runtime'da da mevcut olmasını gerektiriyor — ama Alıştırma 2'nin şablonu `uv` binary'sini yalnızca **builder** aşamasına kopyalıyor (final aşama sadece `/app`'i alıyor, `uv`'yi değil). Bu, "birebir aynı Dockerfile" talimatıyla doğrudan çelişen bir noktaydı; final aşamaya `COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/` satırı eklendi.

**Build sonrası ilk gerçek test başarısız oldu:** `/ask`'a istek atınca `mcp.shared.exceptions.MCPError: Connection closed` — `paper_server.py` alt-process'i başlar başlamaz çöküyordu. `docker exec` ile konteynerin içine girip incelendi; kök sebep, `mcp` kütüphanesinin `StdioServerParameters`'ının alt-process'e **yalnızca güvenli bir allowlist** (`PATH`, `HOME`, `APPDATA` vb. — platforma göre sabit bir liste, kütüphanenin kaynağından doğrulandı) geçirmesi, `GEMINI_API_KEY`'in bu listede **hiç olmaması**. Yerelde bu fark edilmemişti çünkü `paper_server.py`'ın kendi `load_dotenv()`'i diskteki `.env`'i buluyordu; Docker'da `.env`, `.dockerignore` ile hariç tutulduğu için alt-process key'siz kalıyordu. **Çözüm:** `agent_client.py`'de `StdioServerParameters(..., env={"GEMINI_API_KEY": os.environ.get("GEMINI_API_KEY", "")})` ile açıkça geçirildi. Düzeltme sonrası gerçek bir soru ("PubMed'de SSVEP...") konteyner içinde 9.3 saniyede, kaynaklı doğru cevapla sonuçlandı.

### CI

`ci.yml`, rag-literature-assistant'takiyle birebir aynı (`astral-sh/setup-uv@v10.2.0` — `v9` tag'inin olmadığı orada zaten bulunmuştu). İlk çalıştırma **yine** başarısız oldu, ama farklı bir sebeple: `tests/test_agent.py`'nin `from agent_basics import add, multiply, run_agent` satırı, `agent_basics.py`'nin modül seviyesindeki `client = genai.Client()`'ı tetikleyip CI'da (key yok) `ValueError: No API key was provided` ile çöktü. Bu, `agent_client.py`'de FastAPI testleri için zaten düzeltilmiş olan **aynı sınıf sorunun** ikinci bir dosyada (Faz 3'ten kalma, önceden fark edilmemiş) tekrarıydı — hem `agent_client.py` hem `agent_basics.py`'deki `client` tembel bir `_get_client()` fonksiyonuna taşındı. Düzeltme sonrası CI **19 saniyede yeşile döndü** (`gh run view` ile gerçekten izlendi).

### Deploy

Render'a manuel deploy edildi (kullanıcı tarafından — hesap/env var adımları). `GEMINI_API_KEY` eklendi, **`RAG_CHROMA_DB_PATH` bilerek eklenmedi** (Bölüm 4).

**Canlı doğrulama:**
- `/health` → 200, 0.5sn.
- `/ask` (gerçek soru) → 200, 26sn (cold start + `uv run paper_server.py` alt-process başlatma + gerçek PubMed/Gemini çağrıları dahil), doğru PMID'ler ve başlıklarla.

### Deney 7

Canlı URL'e `index_paper`'ı tetikleyecek bir soru ("PMID X'i indeksle") soruldu. Sonuç: **200**, servis çökmedi, agent kullanıcıya "İndeksleme bu ortamda yapılandırılmamış (RAG_CHROMA_DB_PATH ayarlı değil)" mesajını olduğu gibi iletti (23sn). Bölüm 0.6'daki (rag-literature-assistant reposunda) "nazikçe kapat" kararının production'da gerçekten işe yaradığının kanıtı.

---

## 4. Alıştırma 8 — `test_api.py`

`tests/test_api.py`, rag-literature-assistant'takiyle aynı desende ama `ask()` **async** olduğu için `unittest.mock.patch("api.ask", new_callable=AsyncMock, ...)` kullanıyor (düz `patch(..., return_value=...)` async fonksiyon için yanlış olurdu — çağrıldığında bir coroutine değil, doğrudan string dönerdi).

**CI'ya özgü ek bulgu:** `TestClient(app)` (`with` bloğu olmadan) lifespan'ı hiç tetiklemediği için, `api.py`'ye rag-literature-assistant'takiyle aynı desende bir `lifespan` eklenip `GEMINI_API_KEY` kontrolü oraya taşındı — aksi halde bu kontrol de import zamanında CI'yı kırardı. `.env` dosyası **tamamen kaldırılarak** (yalnızca `os.environ`'dan silmek değil) test edildi: 5 test de key'siz, network'süz, 2.1 saniyede geçti.

---

## 5. Karşılaşılan gerçek sorunlar ve çözümleri

| Sorun | Sebep | Çözüm |
|---|---|---|
| `/ask` Windows'ta `fastapi dev` altında sessizce 500 | uvicorn'un `--reload` mekanizması Windows'ta asyncio subprocess desteğini bozuyor | Yerel geliştirme için `uv run uvicorn api:app` (reload'suz) kullan |
| Docker'da `MCPError: Connection closed` | `StdioServerParameters`, alt-process'e `GEMINI_API_KEY`'i içermeyen bir güvenlik allowlist'i geçiriyor; `.env` `.dockerignore`'da olduğu için `paper_server.py`'nin kendi `load_dotenv()`'i de kurtaramıyor | `StdioServerParameters(..., env={"GEMINI_API_KEY": ...})` ile açıkça geçir |
| Final Docker image'da `uv` yok | Alıştırma 2 şablonu `uv`'yi yalnızca builder aşamasına kopyalıyor | Final `FROM` satırına da `COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/` |
| CI: `agent_basics.py` import edilirken `ValueError: No API key` | Modül seviyesinde eager `client = genai.Client()` (Faz 3'te demo çağrısı `__main__` altına alınmıştı ama bu satır unutulmuştu) | `_get_client()` ile tembel açılış |
| `test_ask_endpoint_returns_answer_field` yanlış patch ile yanlış geçerdi | `ask` async; düz `patch(..., return_value=...)` çağrıldığında coroutine değil string döner, `await` hata verirdi | `patch("api.ask", new_callable=AsyncMock, return_value=...)` |

---

## 6. Sınırlamalar (dürüst değerlendirme)

- **`fastapi dev`/reload sorununun kök sebebi tam izole edilmedi:** Gözlem tekrarlanabilir (reload = sessiz 500, reload'suz = çalışır) ama uvicorn/anyio/mcp'nin hangi kesişiminin tam olarak sorumlu olduğu doğrulanmadı; yalnızca Windows'ta gözlendi, Docker'da (Linux) hiç sorun yok.
- **`index_paper` production'da tamamen devre dışı** — bilinçli bir tradeoff, ama bu, roadmap'in "Faz 3 makale bulup Faz 2'nin koleksiyonuna eklesin" hedefinin canlı ortamda çalışmadığı anlamına geliyor. rag-literature-assistant/FAZ4_RAPOR.md Bölüm 9'da önerilen HTTP tabanlı `/index` endpoint'i bu sınırlamayı gerçekten çözerdi.
- **Cold start + alt-process başlatma birikiyor:** Render'ın kendi cold start'ı (~birkaç saniye) ile `uv run paper_server.py`'ın her istekte yeniden başlaması (agent_client.py her `ask()` çağrısında yeni bir `stdio_client` açıyor, subprocess'i **kalıcı tutmuyor**) üst üste biniyor — her istek, bağlantı kalıcı olsaydı gerekmeyecek bir subprocess başlatma maliyeti taşıyor.
- **Eşzamanlılık düşünülmedi:** Aynı anda birden fazla `/ask` isteği gelirse, her biri kendi `paper_server.py` alt-process'ini başlatır; teorik olarak kaynak tüketimi/yarış durumu oluşabilir, bu projede test edilmedi.

---

## 7. Dosya haritası (yeni/değişen dosyalar)

| Dosya | Amaç |
|---|---|
| `api.py` | FastAPI: async `POST /ask`, `GET /health`; `GEMINI_API_KEY` kontrolü `lifespan`'da |
| `Dockerfile` | Çok aşamalı build, **final aşamada da `uv`** (runtime subprocess için) |
| `.dockerignore` | `.venv/`, `tests/`, `.git/`, `.env` vb. |
| `.github/workflows/ci.yml` | Push/PR'da `uv sync` + `pytest` |
| `agent_client.py` (değişti) | `genai.Client()` tembelleştirildi; `StdioServerParameters`'a `env=` eklendi |
| `agent_basics.py` (değişti) | `genai.Client()` tembelleştirildi (CI'ı kıran unutulmuş satır) |
| `tests/test_api.py` | `AsyncMock` ile `/ask`, `/health`, 422 testleri |

**Çalıştırma**
```bash
uv sync
uv run python agent_client.py     # terminal demo
uv run uvicorn api:app --port 8000   # HTTP API (reload'suz!)
docker build -t mcp-api . && docker run -p 8000:8000 --env-file .env mcp-api
uv run pytest -v                  # 5 test
```

---

## 8. Sonraki adım önerileri

1. **`fastapi dev`/reload sorununun kök sebebini izole etmek:** uvicorn'un reload subprocess'inin event loop policy'sini incelemek, minimal bir tekrar üretim (yalnızca `asyncio.create_subprocess_exec` + `--reload`) ile doğrulamak.
2. **Kalıcı MCP bağlantısı:** Her `/ask` isteğinde yeni bir `stdio_client`/subprocess açmak yerine, uygulama başlarken tek bir `ClientSession` açıp isteğe göre yeniden kullanmak (subprocess başlatma maliyetini ortadan kaldırır).
3. **HTTP tabanlı `/index` entegrasyonu:** rag-literature-assistant'a bir `/index` endpoint'i ekleyip, `index_paper`'ın Chroma'ya doğrudan yazmak yerine bu endpoint'i HTTP ile çağırması — iki servisin paylaşılan disk yerine doğru şekilde (API'yle) bağlanması.
