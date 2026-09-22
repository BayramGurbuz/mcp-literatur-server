import os
import xml.etree.ElementTree as ET

import httpx
from dotenv import load_dotenv
from mcp.server.mcpserver import MCPServer

load_dotenv()
mcp = MCPServer("literatur-server")

BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"


@mcp.tool()
def ping(message: str) -> str:
    """Verilen mesajı olduğu gibi geri döndürür (bağlantı testi için)."""
    return f"pong: {message}"


@mcp.tool()
def search_papers(query: str, max_results: int = 5) -> str:
    """PubMed'de verilen sorguyla makale arar, başlık ve PMID listesi döndürür.

    Args:
        query: Arama terimi, örn. "SSVEP brain computer interface"
        max_results: Döndürülecek maksimum makale sayısı
    """
    try:
        search_response = httpx.get(
            f"{BASE_URL}esearch.fcgi",
            params={"db": "pubmed", "term": query, "retmode": "json", "retmax": max_results},
        )
        search_response.raise_for_status()
    except httpx.HTTPError as e:
        return f"PubMed araması başarısız oldu: {e}"

    pmids = search_response.json().get("esearchresult", {}).get("idlist", [])
    if not pmids:
        return "Sonuç bulunamadı."

    try:
        summary_response = httpx.get(
            f"{BASE_URL}esummary.fcgi",
            params={"db": "pubmed", "id": ",".join(pmids), "retmode": "json"},
        )
        summary_response.raise_for_status()
    except httpx.HTTPError as e:
        return f"PubMed özetleri alınamadı: {e}"

    summaries = summary_response.json()["result"]
    lines = []
    for pmid in pmids:
        title = summaries.get(pmid, {}).get("title", "Başlık bulunamadı")
        lines.append(f"PMID {pmid}: {title}")
    return "\n".join(lines)


def _fetch_paper(pmid: str) -> dict | None:
    """PubMed XML'inden tek bir makalenin başlık/abstract/künye alanlarını çeker.

    Faz 2'deki fetch_papers'ın tek-PMID hali — aynı ayrıştırma mantığı.
    Ağ hatası, geçersiz PMID ya da abstract'ı olmayan kayıtlarda None döner.
    """
    try:
        response = httpx.get(
            f"{BASE_URL}efetch.fcgi", params={"db": "pubmed", "id": pmid, "retmode": "xml"}, timeout=30
        )
        response.raise_for_status()
    except httpx.HTTPError:
        return None

    node = ET.fromstring(response.text).find("PubmedArticle")
    if node is None:
        return None
    article = node.find("MedlineCitation/Article")

    abstract_parts = []
    for part in article.findall("Abstract/AbstractText"):
        text = "".join(part.itertext()).strip()
        label = part.get("Label")
        abstract_parts.append(f"{label}: {text}" if label else text)
    if not abstract_parts:
        return None

    pub_date = article.find("Journal/JournalIssue/PubDate")
    year = pub_date.findtext("Year") or (pub_date.findtext("MedlineDate") or "")[:4]
    first_author = article.findtext("AuthorList/Author/LastName") or ""
    return {
        "pmid": node.findtext("MedlineCitation/PMID"),
        "title": "".join(article.find("ArticleTitle").itertext()).strip(),
        "abstract": " ".join(abstract_parts),
        "journal": article.findtext("Journal/Title") or "",
        "year": year,
        "first_author": first_author,
    }


@mcp.tool()
def get_abstract(pmid: str) -> str:
    """Verilen PMID'nin tam başlığını ve abstract'ını döndürür.

    Args:
        pmid: PubMed makale ID'si, örn. "42747938"
    """
    paper = _fetch_paper(pmid)
    if paper is None:
        return f"PMID {pmid} için abstract bulunamadı (geçersiz ID ya da PubMed isteği başarısız oldu)."
    return f"{paper['title']}\n\n{paper['abstract']}"


@mcp.tool()
def index_paper(pmid: str) -> str:
    """Verilen PMID'yi rag-literature-assistant'ın RAG koleksiyonuna indeksler.

    Bu, MCP server'ı hem arama hem de RAG sistemine veri besleme aracı yapar:
    agent önce search_papers ile makale bulur, ilginç bulduğunu index_paper ile
    kalıcı koleksiyona ekler, sonra rag-literature-assistant'ın /ask'ı o makaleyi
    de kullanabilir. Chroma'ya doğrudan yazmak yerine (iki servis artık ayrı
    container'larda/disklerde çalıştığı için paylaşılan dosyaya güvenemiyoruz)
    rag-literature-assistant'ın /index endpoint'ini HTTP üzerinden çağırıyor.

    Args:
        pmid: PubMed makale ID'si, örn. "42747938"
    """
    rag_api_url = os.getenv("RAG_API_URL")
    if not rag_api_url:
        return "İndeksleme bu ortamda yapılandırılmamış (RAG_API_URL ayarlı değil)."

    headers = {}
    index_api_key = os.getenv("INDEX_API_KEY")
    if index_api_key:
        headers["X-Api-Key"] = index_api_key

    try:
        response = httpx.post(f"{rag_api_url}/index", json={"pmid": pmid}, headers=headers, timeout=60)
        response.raise_for_status()
    except httpx.HTTPStatusError as e:
        return f"PMID {pmid} indekslenemedi: rag-literature-assistant {e.response.status_code} döndürdü ({e.response.text})."
    except httpx.HTTPError as e:
        return f"PMID {pmid} indekslenemedi: rag-literature-assistant'a istek başarısız oldu ({e})."

    data = response.json()
    return f"PMID {pmid}, rag-literature-assistant'a {data['chunks']} chunk olarak indekslendi."


if __name__ == "__main__":
    mcp.run()  # varsayılan transport: stdio
