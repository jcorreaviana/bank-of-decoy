"""RAG sobre specs/business/ (mesmo padrao de
distrito-study/usecases/case-one/ingest.py + tools.py::search_policies):
chunking por secao (## heading), embeddings locais via sentence-transformers.

Indice vetorial: numpy + cosseno, persistido em `.npz`/`.json` locais, em
vez de ChromaDB. Decisao de implementacao: `chromadb` depende de
`chroma-hnswlib`, que exige compilar uma extensao C (Microsoft C++ Build
Tools), indisponivel neste ambiente - trocar a ferramenta em vez de exigir
instalar toolchain de compilador so para um indice de ~15 documentos
curtos (specs/business/) mantem o resultado (busca semantica local) sem
essa dependencia de sistema. Suficiente neste volume; nao escalaria para
milhares de documentos sem revisar.
"""

import json
import re
from pathlib import Path

import numpy as np
from sentence_transformers import SentenceTransformer

_REPO_ROOT = Path(__file__).resolve().parents[2]
SPECS_DIR = _REPO_ROOT / "specs" / "business"
INDEX_DIR = Path(__file__).resolve().parent / "rag_index"
EMBEDDINGS_PATH = INDEX_DIR / "embeddings.npy"
METADATA_PATH = INDEX_DIR / "metadata.json"
EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

TOP_K = 4
DISTANCE_THRESHOLD = 4.5
"""Calibrado empiricamente contra specs/business/ real (nao reaproveitado
de distrito-study: aquele projeto usa ChromaDB, cuja distancia "l2" e o
QUADRADO da distancia euclidiana - a escala e diferente da norma euclidiana
pura calculada aqui via numpy). Queries relacionadas ao dominio (ex. "chave
PIX de destino inexistente") ficaram na faixa 2.7-3.7; uma query fora do
dominio ("receita de bolo de chocolate") ficou em 5.6+. 4.5 da margem
segura entre os dois grupos, com a mesma amostra pequena usada em
distrito-study (sem dataset proprio de perguntas/respostas para
recalibrar com mais rigor)."""

_embedding_model = None


def _get_embedding_model():
    global _embedding_model
    if _embedding_model is None:
        _embedding_model = SentenceTransformer(EMBEDDING_MODEL)
    return _embedding_model


def _chunk_by_heading(text: str, file_name: str) -> list[dict]:
    sections = re.split(r"\n(?=## )", text)
    chunks = []
    for section in sections:
        section = section.strip()
        if not section or section.startswith("# "):
            continue
        title_match = re.match(r"## (.+)", section)
        title = title_match.group(1) if title_match else "geral"
        chunks.append({"text": section, "section": title, "file": file_name})
    return chunks


def ingest_specs() -> int:
    """Reindexa todas as specs/business/*.md do zero. Retorna o numero de
    chunks indexados. Rode toda vez que specs/business/ mudar (nao ha
    invalidacao incremental - mesma simplicidade de distrito-study)."""
    chunks: list[dict] = []
    for path in sorted(SPECS_DIR.glob("*.md")):
        if path.name == "README.md":
            continue
        text = path.read_text(encoding="utf-8")
        chunks.extend(_chunk_by_heading(text, path.name))

    model = _get_embedding_model()
    texts = [c["text"] for c in chunks]
    embeddings = model.encode(texts, show_progress_bar=False)

    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    np.save(EMBEDDINGS_PATH, np.asarray(embeddings, dtype=np.float32))
    METADATA_PATH.write_text(json.dumps(chunks, ensure_ascii=False), encoding="utf-8")
    return len(chunks)


def _load_index() -> tuple[np.ndarray, list[dict]]:
    if not EMBEDDINGS_PATH.exists() or not METADATA_PATH.exists():
        raise RuntimeError("Indice RAG nao encontrado - rode rag.ingest_specs() primeiro.")
    embeddings = np.load(EMBEDDINGS_PATH)
    chunks = json.loads(METADATA_PATH.read_text(encoding="utf-8"))
    return embeddings, chunks


def search_specs(query: str, top_k: int = TOP_K, distance_threshold: float = DISTANCE_THRESHOLD) -> list[dict]:
    """Retorna os chunks mais relevantes, cada um com `text`, `file`,
    `section`, `distance` (distancia euclidiana L2, mesma metrica/escala de
    distrito-study). Lista vazia se a menor distancia ultrapassar o
    threshold (nenhum contexto relevante o suficiente)."""
    embeddings, chunks = _load_index()
    model = _get_embedding_model()
    query_embedding = np.asarray(model.encode([query])[0], dtype=np.float32)

    distances = np.linalg.norm(embeddings - query_embedding, axis=1)
    order = np.argsort(distances)[:top_k]

    if len(order) == 0 or distances[order[0]] > distance_threshold:
        return []

    return [
        {"text": chunks[i]["text"], "file": chunks[i]["file"], "section": chunks[i]["section"], "distance": float(distances[i])}
        for i in order
    ]
