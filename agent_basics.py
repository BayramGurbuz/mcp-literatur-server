from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()
_client: genai.Client | None = None


def _get_client() -> genai.Client:
    """Tembel açılır: `tests/test_agent.py`'nin `from agent_basics import add, ...`
    satırı yalnızca import ediyor, GEMINI_API_KEY olmayan bir ortamda (CI) bile
    çökmemesi için `genai.Client()` burada değil, ilk gerçek kullanımda çalışır."""
    global _client
    if _client is None:
        _client = genai.Client()
    return _client


def get_paper_count(search_term: str) -> int:
    """PubMed'de verilen terimle kaç makale olduğunu döndürür (sahte veri, sadece demo).

    Args:
        search_term: Aranacak terim, örn. "ssvep"
    """
    fake_db = {"ssvep": 4231, "p300": 6820, "bci": 15400}
    return fake_db.get(search_term.lower(), 0)


def add(a: float, b: float) -> float:
    """İki sayıyı toplar."""
    return a + b


def multiply(a: float, b: float) -> float:
    """İki sayıyı çarpar."""
    return a * b


TOOLS = {"add": add, "multiply": multiply}


def run_agent(question: str, max_iterations: int = 5) -> str:
    contents = [types.Content(role="user", parts=[types.Part.from_text(text=question)])]
    config = types.GenerateContentConfig(
        tools=[types.Tool(function_declarations=[
            types.FunctionDeclaration(
                name="add", description="İki sayıyı toplar.",
                parameters_json_schema={
                    "type": "object",
                    "properties": {"a": {"type": "number"}, "b": {"type": "number"}},
                    "required": ["a", "b"],
                },
            ),
            types.FunctionDeclaration(
                name="multiply", description="İki sayıyı çarpar.",
                parameters_json_schema={
                    "type": "object",
                    "properties": {"a": {"type": "number"}, "b": {"type": "number"}},
                    "required": ["a", "b"],
                },
            ),
        ])],
        # otomatik çağırmayı KAPATIYORUZ — döngüyü kendimiz yöneteceğiz
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )

    for i in range(max_iterations):
        response = _get_client().models.generate_content(model="gemini-flash-latest", contents=contents, config=config)

        if not response.function_calls:
            return response.text  # model artık tool istemiyor, final cevap bu

        contents.append(response.candidates[0].content)  # modelin "tool çağır" isteğini geçmişe ekle

        response_parts = []
        for fc in response.function_calls:
            print(f"  [Agent] {fc.name}({dict(fc.args)}) çağrılıyor...")
            result = TOOLS[fc.name](**fc.args)
            response_parts.append(types.Part.from_function_response(name=fc.name, response={"result": result}))
        # Gemini "tool" rolünü kabul etmiyor: fonksiyon sonuçları role="user" ile, tek Content içinde gider
        contents.append(types.Content(role="user", parts=response_parts))

    return "Maksimum iterasyona ulaşıldı, cevap üretilemedi."


if __name__ == "__main__":
    # Bu demo çağrılarını guard'ın içine aldık: modül import edildiğinde (örn. testte
    # `from agent_basics import add, multiply, run_agent`) tetiklenmesinler diye —
    # aksi halde her `pytest` çalıştırmasında gerçek Gemini API istekleri gider.
    response = _get_client().models.generate_content(
        model="gemini-flash-latest",
        contents="PubMed'de SSVEP ile ilgili kaç makale var?",
        config=types.GenerateContentConfig(tools=[get_paper_count]),
    )
    print(response.text)

    print(run_agent("(3 + 4) sayısını 5 ile çarpıp bana sonucu söyle."))
