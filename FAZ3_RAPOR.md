# Faz 3 Raporu — MCP Literatür Server'ı

**Proje:** PubMed'de arama yapan, tek bir makalenin abstract'ını getiren ve sonuçları Faz 2'deki RAG koleksiyonuna indeksleyebilen bir MCP (Model Context Protocol) server'ı; bunu bir Gemini agent'ına bağlayan client.
**Klasör:** `Faz 3/mcp-literatur-server/`
**Transport:** stdio (client, server'ı alt-process olarak başlatıp stdin/stdout üzerinden JSON-RPC ile konuşuyor)
**Modeller:** ajan `gemini-flash-latest`, embedding `gemini-embedding-001`
**Kütüphaneler:** `mcp` 2.x (SDK), `google-genai` 2.24.0, `httpx`, `chromadb`, `python-dotenv`

> **Not (Faz 4 sonrası):** Agent modeli maliyet nedeniyle `gemini-2.5-flash`'a düşürüldü; `index_paper` artık Chroma'ya doğrudan yazmıyor, `chromadb` bu repodan tamamen kalktı — bkz. [FAZ4_RAPOR.md](FAZ4_RAPOR.md) Bölüm 9-10. Aşağıdaki içerik, o zamanki tasarımın tarihsel bir kaydı olarak değiştirilmedi.

---

## 1. Özet

Faz 3'te üç parça uçtan uca birleştirildi:

1. **`paper_server.py`** — 4 tool sunan bir MCP server: `ping` (bağlantı testi), `search_papers` (PubMed arama), `get_abstract` (tek makalenin tam metni), `index_paper` (Faz 2'nin Chroma koleksiyonuna yazma).
2. **`agent_client.py`** — server'ı kendi başlatan, `google-genai`'nin deneysel yerli MCP desteğiyle (`tools=[session]`) bir `ClientSession`'ı doğrudan Gemini'ye tool olarak veren asenkron client.
3. **`agent_basics.py` + `tests/test_agent.py`** — function-calling temelleri (elle yazılmış `FunctionDeclaration`, kendi yönettiğin çok-adımlı `run_agent` döngüsü) ve bunun deterministik kısımları için birim testler.

Kod, kurulu kütüphane sürümleriyle üç yerde ders materyalinden **farklı** davranıyordu; bunlar çalıştırılıp gözlemlenerek düzeltildi (bkz. Bölüm 5). Ayrıca çok adımlı MCP akışı (arama → abstract getirme → özetleme) ve `index_paper`'ın Faz 2'nin gerçek veritabanına yazdığı, gerçek isteklerle doğrulandı.

---

## 2. Mimari

```
Gemini agent (agent_client.py, async)
        │  client.aio.models.generate_content(config={"tools": [session]})
        ▼
 ClientSession  ──stdio (JSON-RPC)──►  paper_server.py (alt-process, "uv run" ile başlar)
        │                                     │
        │  1) list_tools()                    ├─ ping(message)
        │  2) call_tool(isim, argümanlar)      ├─ search_papers(query, max_results)  ──► PubMed esearch+esummary
        │                                      ├─ get_abstract(pmid)                 ──► PubMed efetch (XML)
        │                                      └─ index_paper(pmid)                  ──► efetch + embed_content
        │                                                                                  + Chroma upsert
        ▼                                                                                        │
   response.text                                                                                  ▼
                                                                                   Faz 2/rag-literature-assistant/
                                                                                   chroma_db  (koleksiyon: bci_abstracts)
```

**Önemli tasarım kararı:** `index_paper`, Faz 3'e özel yeni bir veritabanı açmıyor; `Path(__file__).resolve().parents[2] / "Faz 2" / "rag-literature-assistant" / "chroma_db"` ile **doğrudan Faz 2'nin kalıcı koleksiyonuna** yazıyor. Bu, iki fazı gerçekten birleştiriyor: Faz 3'ün agent'ı bulduğu bir makaleyi indekslerse, Faz 2'nin `main.py`'ındaki sohbet döngüsü bir sonraki çalıştırmada o makaleyi de kullanabilir.

---

## 3. Alıştırmalar

### Alıştırma 1-2 — Function calling temelleri (`agent_basics.py`)
Bu fazın başında hazırdı. `get_paper_count` ile tek fonksiyonlu, SDK'nın otomatik çağırdığı basit bir örnek; ardından `add`/`multiply` için elle yazılmış `FunctionDeclaration` şemalarıyla, **otomatik çağırmayı kapatıp** (`automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True)`) döngüyü kendin yönettiğin bir `run_agent` fonksiyonu. Bu elle yazılan döngü, Alıştırma 5'te MCP + `google-genai`'nin yerli desteğiyle SDK'ya devredilen kısmın referans noktası oldu.

### Alıştırma 3 — MCP nedir, ilk server
`paper_server.py` oluşturuldu: `FastMCP("literatur-server")` ve tek bir `ping` tool'u.

**Kurulu sürümle uyuşmazlık:** Ders kodu `from mcp.server.fastmcp import FastMCP` kullanıyordu; bu, `mcp` kütüphanesinin 1.x API'si. Projenin `pyproject.toml`'ı (`mcp>=2.2.0`) ve kilitli `uv.lock` **2.x**'i getiriyor, ve o sürümde `FastMCP` → `MCPServer` olarak yeniden adlandırılmış (`mcp.server.mcpserver.MCPServer`). Import düzeltilip doğrulandı.

**Deney 3 (server'ın sessizliği):** `uv run python paper_server.py`, stdin bağlı bir client olmadan çalıştırıldı (`< /dev/null`, 5 sn zaman aşımı). Çıktı: **hiçbir şey** — ne hata, ne prompt. Server, stdin'den bir JSON-RPC isteği bekleyen pasif bir process; kendiliğinden bir işlem başlatmıyor.

### Alıştırma 4 — `search_papers` tool'unu server'a taşı
`esearch.fcgi` (PMID listesi) + `esummary.fcgi` (başlıklar) ile PubMed araması yapan `search_papers` tool'u eklendi; `agent_client.py` (düşük seviye `ClientSession` ile bağlantı testi) yazıldı.

Gerçek bir sorguyla test edildi (`query="SSVEP", max_results=3`):
```
Sunucudaki tool'lar: ['ping', 'search_papers']
PMID 42747938: Calibration-Efficient Dual-Frequency SSVEP-BCI for Head-Mounted AR-Based UAV Control.
PMID 42747931: SPAR-EEG: Selective Pass-Wise Artifact Reduction for Wearable Single-Channel EEG Denoising.
PMID 42731193: Selective Attention Deficits in Mild Traumatic Brain Injury using SSVEP...
```
**Deney 4** (bilerek `"db": "pubmeddd"` yapıp hatanın nereye sızdığını gözlemlemek) alıştırma metninde tarif edildi ve `search_papers`'ın o an henüz try/except içermediği doğrulandı; bu gözlem doğrudan Bölüm 4.2'deki hata yönetimi eklemesinin gerekçesi oldu.

### Alıştırma 5 — Gemini agent + MCP server birleştirmesi
`agent_client.py`, `ClientSession`'ı doğrudan `tools=` listesine veren, asenkron (`client.aio.models.generate_content`) bir akışa dönüştürüldü — SDK, server'daki tool'ları otomatik keşfedip şemaya çeviriyor ve çağırıyor (Alıştırma 1-2'de elle yazdığın adımların SDK tarafından yapılan hali).

**Kurulu sürümle uyuşmazlık:** Ders kodundaki `config=types.GenerateContentConfig(tools=[session])` şu hatayla çöktü:
```
TypeError: cannot pickle '_asyncio.Task' object
```
Sebep: `google-genai`'nin `generate_content`'i, session'ı gerçek bir tool'a çevirmeden **önce** `config.model_copy(deep=True)` çağırıyor; `ClientSession`'ın içindeki canlı `asyncio.Task` deep-copy'lenemiyor (`google-genai==2.24.0`, Python 3.11, Windows). **Çözüm:** config'i `types.GenerateContentConfig` nesnesi değil, düz bir **dict** olarak vermek (`config={"tools": [session]}`) — SDK farklı bir kod yoluna girip bu deep-copy'yi atlıyor. Fonksiyonel olarak aynı, sadece bu sürümdeki çökmeyi bertaraf ediyor.

Gerçek soruyla test edildi ("PubMed'de P300 speller ile ilgili son çalışmalardan 3 tanesi"), üç gerçek PMID ve başlıkla cevap geldi.

**Deney 5** (`config` kaldırılıp aynı soru sorulması) kullanıcı tarafından bizzat çalıştırıldı: model **halüsine edilmiş çıktılar** verdi — inandırıcı görünen ama var olmayan/doğrulanmamış başlık ve PMID'ler. Bu, Alıştırma 1 ve Faz 2 Alıştırma 5'teki "tool'suz model, bilmediği yerde uydurur" dersinin MCP bağlamında üçüncü doğrulanışı.

### Alıştırma 6 — Test
`pytest` proje bağımlılıklarında yoktu; Faz 1/2'deki desenle (`[dependency-groups] dev = ["pytest>=9.1.1"]`, `[tool.pytest.ini_options] pythonpath = ["."]`) eklendi. `tests/test_agent.py`, `add`/`multiply` gibi saf fonksiyonları test ediyor; `run_agent` gerçek API çağırdığı için (deterministik değil, yavaş, maliyetli) test edilmiyor — notta `unittest.mock` ile `generate_content`'i sahteleyip agent mantığını LLM'den izole test etme fikri bırakıldı.

**Bulunan gerçek sorun:** `agent_basics.py`'ın modül seviyesinde (herhangi bir fonksiyon/guard dışında) gerçek bir `client.models.generate_content(...)` çağrısı vardı (Alıştırma 1'den kalma demo). Python bir modülü import ederken dosyayı baştan sona çalıştırdığı için, `test_agent.py`'daki `from agent_basics import ...` satırı **her `pytest` çalıştırmasında** gerçek bir Gemini API isteği tetikliyordu (`pytest -v -s` ile doğrulandı — test toplama aşamasında modelin cevabı ekrana basılıyordu). Bu, alıştırmanın kendi ilkesine ("API'ye/network'e dokunmayan deterministik test") aykırıydı. **Düzeltme:** her iki demo çağrısı (module-level olan ve `run_agent` çağrısı) tek bir `if __name__ == "__main__":` bloğunda birleştirildi. Sonuç: `pytest` süresi 4.49 sn → 0.99 sn'ye düştü ve test toplama sırasında artık hiçbir ağ isteği gitmiyor; `python agent_basics.py` ile doğrudan çalıştırıldığında demo'lar hâlâ çalışıyor.

---

## 4. Proje: Hepsini Birleştir

### 4.1 `get_abstract(pmid) -> str`
`efetch.fcgi` (XML) üzerinden tek bir PMID'nin başlığını ve tam abstract'ını çeken `_fetch_paper` yardımcı fonksiyonu eklendi — Faz 2'deki `fetch_papers`'ın aynı XML ayrıştırma mantığının tek-PMID hali (etiketli abstract bölümleri, yıl, ilk yazar). Geçersiz PMID veya ağ hatasında `None` döner, tool bunu kullanıcı dostu bir mesaja çevirir.

Test edildi: geçerli PMID (42747938) için başlık+abstract geldi; geçersiz PMID (`99999999999`) için `"...abstract bulunamadı (geçersiz ID ya da PubMed isteği başarısız oldu)."` mesajı döndü, hata fırlatmadı.

### 4.2 Hata yönetimi (`search_papers`)
`esearch`/`esummary` çağrıları `try/except httpx.HTTPError` içine alındı. Bozuk bir domain'e (`https://this-domain-does-not-exist-xyz123.invalid/`) yönlendirilerek test edildi: server çökmek yerine `"PubMed araması başarısız oldu: [Errno 11001] getaddrinfo failed"` gibi bir mesaj döndürdü — Deney 4'ün işaret ettiği eksiklik kapatıldı.

### 4.3 `index_paper(pmid) -> str` — Faz 2 ile gerçek birleşme
`_fetch_paper` ile makaleyi çekip, Faz 2'deki `chunk_sentences` mantığını (cümle sınırlarında ≤800 karakter, chunk başına başlık) birebir uygulayan `_chunk_sentences`, sonra `gemini-embedding-001` ile embed edip Faz 2'nin `bci_abstracts` koleksiyonuna `upsert` ediyor. Chroma bağlantısı, server başlarken değil **ilk `index_paper` çağrısında** tembel açılıyor (`_get_collection`, modül-seviyesi `None` → ilk kullanımda başlatma) — Alıştırma 6'daki dersle aynı sebep: import/başlatma anında ağır iş yapmamak.

**Gerçek veritabanıyla doğrulama:**
- Zaten indekslenmiş bir PMID (42747938) tekrar `index_paper`'a verildi: `upsert` idempotent çalıştı, koleksiyon 82 chunk'ta sabit kaldı.
- Tamamen alakasız, önceden koleksiyonda olmayan bir PMID (`37875091`, "Neural control of cephalopod camouflage") indekslendi: koleksiyon **82 → 84 chunk**'a çıktı, kayıtlar `collection.get` ile doğrulandı. Test amaçlı olduğu için ardından **silindi** (`collection.delete(where={"pmid": "37875091"})`) — Faz 2'nin gerçek BCI koleksiyonunda kalıcı bir iz bırakılmadı, sayı 82'ye geri döndü.
- Embedding isteği başarısız olursa (`errors.APIError`) tool, ham exception yerine `"...embedding isteği başarısız oldu (...)."` mesajı döndürüyor.

### 4.4 Çok adımlı akış — uçtan uca doğrulama
`agent_client.py` üzerinden gerçek bir soru soruldu: *"PubMed'de SSVEP ile ilgili 2 makale bul, sonra ilk bulduğun makalenin PMID'si için abstract'ını getir ve tek cümlede özetle."* Gemini, sırasıyla `search_papers` ve `get_abstract`'ı kendiliğinden çağırdı (SDK'nın otomatik function calling'i), iki makaleyi listeledi ve ilkinin abstract'ını Türkçe tek cümlede özetledi. Bu, roadmap'in "agent önce arar, sonra ilginç bulduğu makale için abstract çeker" hedefinin gerçekten çalıştığının kanıtı.

---

## 5. Karşılaşılan gerçek sorunlar ve çözümleri

| Sorun | Sebep | Çözüm |
|---|---|---|
| `ModuleNotFoundError: mcp.server.fastmcp` | Kurulu `mcp` 2.x'te `FastMCP` → `MCPServer` adı değişti | `from mcp.server.mcpserver import MCPServer` |
| `TypeError: cannot pickle '_asyncio.Task'` | `google-genai` async `generate_content`, `ClientSession`'ı tool'a çevirmeden önce `config.model_copy(deep=True)` çağırıyor | `config=types.GenerateContentConfig(...)` yerine düz `dict` (`config={"tools": [session]}`) |
| `pytest` her çalıştığında gerçek Gemini API isteği gidiyordu | `agent_basics.py`'da modül-seviyesi (guard'sız) API çağrısı, import'ta tetikleniyordu | Demo çağrısı `if __name__ == "__main__":` içine taşındı |
| `search_papers` ağ hatasında server'ı çökertiyordu | `httpx.HTTPError` yakalanmıyordu | `try/except httpx.HTTPError`, anlamlı mesaj döndürme |
| `pytest` kurulu değildi, `tests/` boştu | Proje `dev` dependency group'u yoktu | `uv add --dev pytest` + `pythonpath = ["."]` (Faz 1/2'deki desenle aynı) |
| Windows konsolunda Türkçe karakterler bozuk görünüyordu (`ba�l�k`) | Terminalin kod sayfası UTF-8 değil | Kodun kendisiyle ilgisi yok; PowerShell'de/`-X utf8` ile doğru görünür |
| `import chromadb`/`dotenv`/`google.genai` için IDE uyarısı | VS Code, proje `.venv`'ini yorumlayıcı olarak seçmemiş | Kod çalışıyor (`uv run` ile doğrulandı); IDE ayarı, kod hatası değil |

---

## 6. Testler

`uv run pytest -v` → **2 test geçiyor** (`test_add`, `test_multiply`), ~1 sn, hiçbir ağ isteği yapmadan.

`paper_server.py`'daki yeni tool'lar (`get_abstract`, `search_papers`'ın hata yolu, `index_paper`) için otomatik test **yazılmadı** — hepsi gerçek PubMed/Chroma/Gemini istekleriyle elle doğrulandı (Bölüm 4). Faz 2'deki gibi bunları da deterministik hale getirmek istersen: `_fetch_paper`'ı `httpx.get`'i monkeypatch'leyerek, `_chunk_sentences`'ı ise saf girdi/çıktı olarak (API'siz) test edebilirsin — bu, Bölüm 9'da bir sonraki adım olarak bırakıldı.

---

## 7. Sınırlamalar (dürüst değerlendirme)

- **`paper_server.py`'ın yeni tool'ları test edilmedi (otomatik olarak):** Doğrulama gerçek isteklerle elle yapıldı, regresyona karşı koruma yok.
- **`config={"tools": [session]}` workaround'u sürüme bağlı:** `google-genai` bir sonraki sürümde bu deep-copy hatasını düzeltirse (ya da başka bir hata ekleyebilirse) tekrar test edilmeli.
- **`index_paper`, Faz 2'nin `retrieve`/eşik mantığını (Faz 2 Bölüm 5) tekrar kullanmıyor:** yeni eklenen makale koleksiyona giriyor ama arama tarafındaki mesafe eşikleri (`MAX_DISTANCE=0.65` vb.) Faz 2 kodunda sabit, burada yeniden ölçülmedi.
- **Tek kaynak:** yalnızca PubMed; roadmap'in "PubMed/arXiv" hedefindeki arXiv kısmı yapılmadı.
- **Claude Desktop'a bağlama yapılmadı:** roadmap'in son cümlesi ("MCP server yaz, Claude Desktop'a bağla") bu raporun kapsamı dışında bırakıldı (bkz. Bölüm 9).
- **Eşzamanlılık/çoklu client düşünülmedi:** `_collection` modül-seviyesi tekil bir global; server aynı anda birden fazla client'a hizmet ederse (bu projede olmuyor, ama teorik olarak) yarış durumu oluşabilir.

---

## 8. Dosya haritası

| Dosya | Amaç |
|---|---|
| `paper_server.py` | MCP server: `ping`, `search_papers`, `get_abstract`, `index_paper` |
| `agent_client.py` | Server'ı başlatıp Gemini'ye MCP session'ı tool olarak veren asenkron client |
| `agent_basics.py` | Function-calling temelleri: elle yazılmış `FunctionDeclaration`, elle yönetilen `run_agent` döngüsü |
| `tests/test_agent.py` | `add`/`multiply` için deterministik birim testler |
| `.env` | `GEMINI_API_KEY` (`.gitignore`'da) |
| `chroma_db/` | **Bu klasörde yok** — `index_paper`, Faz 2'nin `../../Faz 2/rag-literature-assistant/chroma_db`'sine yazıyor |

**Çalıştırma**
```powershell
cd "Faz 3\mcp-literatur-server"
uv run python paper_server.py     # tek başına: sessiz bekler (Deney 3), Ctrl+C ile çık
uv run python agent_client.py     # server'ı kendi başlatır, MCP tool'larıyla soru cevaplar
uv run pytest -v                  # testler
```

---

## 9. Sonraki adım önerileri

1. **Claude Desktop'a bağlama:** `claude_desktop_config.json`'a `mcpServers` girdisi eklemek (`command`, `args` — Windows'ta mutlak yollarla `uv run --directory ... paper_server.py`), roadmap'in son adımı.
2. **Yeni tool'lar için otomatik test:** `_fetch_paper` ve `search_papers`'ın hata yolunu `httpx.get`'i monkeypatch'leyerek, `_chunk_sentences`'ı saf girdi/çıktıyla test etmek (Faz 2'deki `test_main.py` deseniyle aynı).
3. **`run_agent` için mock testi:** Alıştırma 6'nın notunda bırakılan fikir — `unittest.mock` ile `client.models.generate_content`'i sahte tool-call cevapları döndürecek şekilde değiştirip döngü mantığını LLM'den bağımsız test etmek.
4. **İkinci kaynak (arXiv):** roadmap'in "PubMed/arXiv" hedefini tamamlamak için `search_papers`'a arXiv API'sini de ekleyen bir varyant ya da ikinci bir tool.
5. **`google-genai` sürüm takibi:** `config={"tools": [session]}` workaround'unun hâlâ gerekli olup olmadığını yeni sürümlerde tekrar kontrol etmek.
