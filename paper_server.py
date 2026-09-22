import re
import xml.etree.ElementTree as ET
from pathlib import Path

import chromadb
import httpx
from dotenv import load_dotenv
from google import genai
from google.genai import errors, types
from mcp.server.mcpserver import MCPServer

load_dotenv()
mcp = MCPServer("literatur-server")
client = genai.Client()

BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
# Faz 2'deki RAG pipeline'ının kullandığı aynı kalıcı Chroma koleksiyonu — index_paper
# buraya yazarak iki fazı gerçekten birleştiriyor (ayrı bir Faz 3 veritabanı değil).
CHROMA_DB_PATH = Path(__file__).resolve().parents[2] / "Faz 2" / "rag-literature-assistant" / "chroma_db"
COLLECTION_NAME = "bci_abstracts"
METADATA_FIELDS = ("pmid", "title", "journal", "year", "first_author")

_collection: chromadb.Collection | None = None  # ilk index_paper çağrısında açılır


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


def _chunk_sentences(title: str, abstract: str, max_chars: int = 800) -> list[str]:
    """Abstract'ı cümle sınırlarında böler; her chunk'ın başına makale başlığını ekler.

    Faz 2'deki chunk_sentences ile birebir aynı — aynı koleksiyona yazdığımız için
    chunk formatı orada indekslenmiş makalelerle tutarlı olmalı.
    """
    sentences = re.split(r"(?<=[.!?])\s+", abstract)
    groups: list[str] = []
    current = ""
    for sentence in sentences:
        if current and len(current) + 1 + len(sentence) > max_chars:
            groups.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        groups.append(current)
    return [f"{title}\n\n{g}" for g in groups]


def _get_collection() -> chromadb.Collection:
    """Faz 2'nin Chroma koleksiyonunu tembel açar (server başlarken değil, ilk kullanımda)."""
    global _collection
    if _collection is None:
        chroma_client = chromadb.PersistentClient(path=str(CHROMA_DB_PATH))
        _collection = chroma_client.get_or_create_collection(name=COLLECTION_NAME)
    return _collection


@mcp.tool()
def index_paper(pmid: str) -> str:
    """Verilen PMID'yi Faz 2'deki RAG koleksiyonuna (bci_abstracts) indeksler.

    Bu, MCP server'ı hem arama hem de RAG sistemine veri besleme aracı yapar:
    agent önce search_papers ile makale bulur, ilginç bulduğunu index_paper ile
    kalıcı koleksiyona ekler, sonra Faz 2'deki chat_loop o makaleyi de kullanabilir.

    Args:
        pmid: PubMed makale ID'si, örn. "42747938"
    """
    paper = _fetch_paper(pmid)
    if paper is None:
        return f"PMID {pmid} indekslenemedi: abstract bulunamadı ya da PubMed isteği başarısız oldu."

    chunks = _chunk_sentences(paper["title"], paper["abstract"])
    try:
        response = client.models.embed_content(
            model="gemini-embedding-001",
            contents=chunks,
            config=types.EmbedContentConfig(task_type="RETRIEVAL_DOCUMENT"),
        )
    except errors.APIError as e:
        return f"PMID {pmid} indekslenemedi: embedding isteği başarısız oldu ({e})."
    embeddings = [e.values for e in response.embeddings]

    ids = [f"{paper['pmid']}_{i}" for i in range(len(chunks))]
    metadatas = [{k: paper[k] for k in METADATA_FIELDS} for _ in chunks]
    # add yerine upsert: aynı PMID tekrar indekslenirse hata vermesin
    _get_collection().upsert(ids=ids, embeddings=embeddings, documents=chunks, metadatas=metadatas)
    return f"PMID {pmid} ({paper['title']}) {len(chunks)} chunk olarak '{COLLECTION_NAME}' koleksiyonuna indekslendi."


if __name__ == "__main__":
    mcp.run()  # varsayılan transport: stdio
