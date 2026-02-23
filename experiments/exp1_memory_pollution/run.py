"""
NAIL Institute — Experiment 1: Tragedy of the Commons (Memory Pollution)
=========================================================================

GOAL: Prove that a shared multi-agent memory space degrades over time
      and test whether an "Archivist Agent" can prevent contextual collapse.

SETUP:
  - Shared ChromaDB vector database
  - 3 Research Agents ingest documents (50 relevant + 10 irrelevant PDFs)
  - 1 Decision Agent answers 20 questions by querying the shared DB
  - CONTROL: No archivist — standard RAG dump
  - VARIABLE: Archivist Agent monitors, compresses, and prunes the DB

METRICS:
  - Decision Agent accuracy (% correct answers)
  - Vector DB size over time (number of embeddings, total tokens)
  - Retrieval precision (relevant vs irrelevant chunks returned)

USAGE:
  conda activate nail_experiments
  python -m exp1_memory_pollution.run
"""

import os
import sys
import json
import time
import hashlib
from pathlib import Path
from typing import Optional

import chromadb
from sentence_transformers import SentenceTransformer

# Add parent to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from shared.config import (
    PRIMARY_MODEL, FAST_MODEL, CHROMA_PERSIST_DIR,
    DATA_DIR, DEFAULT_TEMPERATURE,
)
from shared.ollama_llm import OllamaLLM
from shared.agent_base import Agent
from shared.logger import ExperimentLogger


# ─── Synthetic Dataset Generator ─────────────────────────────────────────────
# Since we may not have 60 PDFs on hand, we generate synthetic documents
# using the local LLM itself. This is actually more controlled for research.

TOPIC = "quantum computing hardware architectures"
NUM_RELEVANT_DOCS = 50
NUM_IRRELEVANT_DOCS = 10
NUM_QUESTIONS = 20
CHUNK_SIZE = 512  # characters per chunk


def generate_synthetic_documents(llm: OllamaLLM, logger: ExperimentLogger) -> tuple[list[dict], list[dict]]:
    """
    Generate synthetic 'documents' using the LLM.
    Returns (relevant_docs, irrelevant_docs).
    Each doc = {"id": str, "title": str, "content": str, "relevant": bool}
    """
    docs_dir = DATA_DIR / "exp1_docs"
    docs_dir.mkdir(exist_ok=True)
    cache_file = docs_dir / "synthetic_docs.json"

    # Use cache if exists
    if cache_file.exists():
        logger.log_event("info", message="Loading cached synthetic documents...")
        with open(cache_file) as f:
            all_docs = json.load(f)
        relevant = [d for d in all_docs if d["relevant"]]
        irrelevant = [d for d in all_docs if not d["relevant"]]
        logger.log_event("info", message=f"Loaded {len(relevant)} relevant, {len(irrelevant)} irrelevant docs")
        return relevant, irrelevant

    logger.log_event("info", message=f"Generating {NUM_RELEVANT_DOCS} relevant + {NUM_IRRELEVANT_DOCS} irrelevant synthetic documents...")

    relevant_docs = []
    subtopics = [
        "superconducting qubits", "trapped ion quantum computers",
        "topological qubits", "photonic quantum computing",
        "quantum error correction codes", "quantum gate fidelity",
        "dilution refrigerators for quantum", "quantum volume metrics",
        "NISQ era algorithms", "quantum annealing vs gate-based",
        "IBM quantum roadmap", "Google Sycamore architecture",
        "IonQ trapped ion systems", "Rigetti hybrid computing",
        "quantum interconnects", "cryogenic control electronics",
        "qubit coherence times", "quantum memory architectures",
        "surface codes for error correction", "quantum compilation techniques",
        "variational quantum eigensolver", "quantum approximate optimization",
        "Majorana fermions for computing", "silicon spin qubits",
        "neutral atom quantum computing",
    ]

    for i in range(NUM_RELEVANT_DOCS):
        subtopic = subtopics[i % len(subtopics)]
        prompt = (
            f"Write a detailed 300-word technical summary about: {subtopic}. "
            f"Focus on specific technical details, numbers, and recent developments. "
            f"This is for a research database on {TOPIC}."
        )
        resp = llm.generate(prompt, temperature=0.8)
        doc = {
            "id": f"rel_{i:03d}",
            "title": f"{subtopic.title()} — Summary {i+1}",
            "content": resp.content,
            "relevant": True,
            "subtopic": subtopic,
        }
        relevant_docs.append(doc)
        logger.log_event("info", message=f"Generated relevant doc {i+1}/{NUM_RELEVANT_DOCS}: {subtopic}")

    # Irrelevant docs — completely off-topic
    irrelevant_topics = [
        "medieval European cooking techniques",
        "19th century railroad expansion in America",
        "tropical fish aquarium maintenance",
        "history of reggae music in Jamaica",
        "competitive dog grooming championships",
        "ancient Roman aqueduct engineering",
        "modern interpretive dance theory",
        "sourdough bread fermentation science",
        "competitive hot dog eating records",
        "origami paper folding mathematics",
    ]

    irrelevant_docs = []
    for i, topic in enumerate(irrelevant_topics[:NUM_IRRELEVANT_DOCS]):
        prompt = f"Write a detailed 300-word article about: {topic}. Include specific facts and details."
        resp = llm.generate(prompt, temperature=0.9)
        doc = {
            "id": f"irr_{i:03d}",
            "title": f"{topic.title()} — Article",
            "content": resp.content,
            "relevant": False,
            "subtopic": topic,
        }
        irrelevant_docs.append(doc)
        logger.log_event("info", message=f"Generated irrelevant doc {i+1}/{NUM_IRRELEVANT_DOCS}: {topic}")

    # Cache
    all_docs = relevant_docs + irrelevant_docs
    with open(cache_file, "w") as f:
        json.dump(all_docs, f, indent=2)

    return relevant_docs, irrelevant_docs


def chunk_document(doc: dict, chunk_size: int = CHUNK_SIZE) -> list[dict]:
    """Split a document into chunks for embedding."""
    text = doc["content"]
    chunks = []
    for i in range(0, len(text), chunk_size):
        chunk_text = text[i:i + chunk_size]
        chunk_id = f"{doc['id']}_chunk_{i // chunk_size}"
        chunks.append({
            "id": chunk_id,
            "doc_id": doc["id"],
            "text": chunk_text,
            "relevant": doc["relevant"],
            "title": doc["title"],
        })
    return chunks


def generate_evaluation_questions(llm: OllamaLLM, logger: ExperimentLogger) -> list[dict]:
    """Generate evaluation questions with ground truth answers."""
    cache_file = DATA_DIR / "exp1_docs" / "eval_questions.json"
    if cache_file.exists():
        with open(cache_file) as f:
            return json.load(f)

    logger.log_event("info", message=f"Generating {NUM_QUESTIONS} evaluation questions...")

    prompt = f"""Generate exactly {NUM_QUESTIONS} highly specific technical questions about {TOPIC}.
For each question, provide the expected answer.

Output as a JSON array of objects with "question" and "expected_answer" keys.
Example:
[
  {{"question": "What is the typical coherence time of superconducting transmon qubits?", "expected_answer": "Typically 50-100 microseconds for state-of-the-art transmon qubits"}},
  ...
]

Generate {NUM_QUESTIONS} questions covering diverse subtopics. Output ONLY valid JSON."""

    resp = llm.generate(prompt, json_mode=True, temperature=0.3)

    try:
        questions = json.loads(resp.content)
        if isinstance(questions, dict) and "questions" in questions:
            questions = questions["questions"]
    except json.JSONDecodeError:
        # Fallback: parse manually
        logger.log_event("error", message="Failed to parse questions JSON, using defaults")
        questions = [
            {"question": f"Question {i+1} about {TOPIC}", "expected_answer": "N/A"}
            for i in range(NUM_QUESTIONS)
        ]

    questions = questions[:NUM_QUESTIONS]
    with open(cache_file, "w") as f:
        json.dump(questions, f, indent=2)

    return questions


# ─── Research Agent ──────────────────────────────────────────────────────────

class ResearchAgent(Agent):
    """Agent that reads documents and stores summaries in ChromaDB."""

    def __init__(self, name: str, model: str, collection, embedder, logger):
        super().__init__(
            name=name,
            role="researcher",
            system_prompt=(
                "You are a thorough research analyst. When given a document, "
                "create a concise but detailed summary capturing ALL key facts, "
                "numbers, and technical details. Preserve specific data points."
            ),
            model=model,
            logger=logger,
        )
        self.collection = collection
        self.embedder = embedder

    def ingest_documents(self, docs: list[dict]):
        """Summarize and embed documents into shared ChromaDB."""
        for doc in docs:
            summary = self.respond_stateless(
                f"Summarize this document in 2-3 dense paragraphs, preserving all "
                f"specific facts and numbers:\n\nTitle: {doc['title']}\n\n{doc['content']}"
            )

            # Chunk the summary
            chunks = chunk_document({**doc, "content": summary})
            for chunk in chunks:
                embedding = self.embedder.encode(chunk["text"]).tolist()
                self.collection.add(
                    ids=[chunk["id"]],
                    embeddings=[embedding],
                    documents=[chunk["text"]],
                    metadatas=[{
                        "doc_id": chunk["doc_id"],
                        "relevant": str(chunk["relevant"]),
                        "title": chunk["title"],
                        "agent": self.name,
                    }],
                )
            self.logger.log_event(
                "info", agent=self.name,
                message=f"Ingested: {doc['title']} ({len(chunks)} chunks)",
            )


# ─── Archivist Agent ─────────────────────────────────────────────────────────

class ArchivistAgent(Agent):
    """
    Agent that monitors and prunes the shared memory.
    Does NOT do research — only maintenance.
    """

    def __init__(self, model: str, collection, embedder, logger):
        super().__init__(
            name="Archivist",
            role="archivist",
            system_prompt=(
                "You are a strict information quality auditor. Your job is to evaluate "
                "whether text chunks in a knowledge base are relevant to the topic: "
                f"'{TOPIC}'. For each chunk, respond with ONLY a JSON object: "
                '{"relevant": true/false, "confidence": 0.0-1.0, "reason": "brief reason"}.'
            ),
            model=model,
            logger=logger,
        )
        self.collection = collection
        self.embedder = embedder

    def audit_and_prune(self, topic_query: str = TOPIC) -> dict:
        """
        Scan the entire collection, evaluate relevance, and remove irrelevant chunks.
        Returns stats on what was kept vs pruned.
        """
        results = self.collection.get(include=["documents", "metadatas"])
        total = len(results["ids"])
        pruned = 0
        kept = 0

        self.logger.log_event("info", agent=self.name, message=f"Auditing {total} chunks in shared memory...")

        for i, (doc_id, text, meta) in enumerate(zip(results["ids"], results["documents"], results["metadatas"])):
            verdict = self.respond_stateless(
                f"Is this text chunk relevant to '{TOPIC}'?\n\nChunk:\n{text[:800]}",
                json_mode=True,
            )
            try:
                parsed = json.loads(verdict)
                is_relevant = parsed.get("relevant", True)
                confidence = parsed.get("confidence", 0.5)
            except (json.JSONDecodeError, AttributeError):
                is_relevant = True  # conservative: keep if unsure
                confidence = 0.5

            if not is_relevant and confidence > 0.7:
                self.collection.delete(ids=[doc_id])
                pruned += 1
                self.logger.log_event(
                    "info", agent=self.name,
                    message=f"PRUNED chunk {doc_id} (conf={confidence:.2f})",
                )
            else:
                kept += 1

        stats = {
            "total_audited": total,
            "pruned": pruned,
            "kept": kept,
            "prune_ratio": round(pruned / max(total, 1), 3),
        }
        self.logger.log_event("metric", agent=self.name, data=stats, message=f"Audit complete: {stats}")
        return stats


# ─── Decision Agent ──────────────────────────────────────────────────────────

class DecisionAgent(Agent):
    """Agent that answers questions by querying the shared ChromaDB."""

    def __init__(self, model: str, collection, embedder, logger):
        super().__init__(
            name="DecisionMaker",
            role="decision_maker",
            system_prompt=(
                "You are a precise question-answering agent. You will be given context "
                "retrieved from a knowledge base. Answer the question using ONLY the provided "
                "context. If the context doesn't contain enough information, say 'INSUFFICIENT DATA'. "
                "Be specific and cite details from the context."
            ),
            model=model,
            logger=logger,
        )
        self.collection = collection
        self.embedder = embedder

    def answer_question(self, question: str, n_results: int = 5) -> dict:
        """Query ChromaDB and answer a question."""
        # Embed the question
        q_embedding = self.embedder.encode(question).tolist()

        # Retrieve
        results = self.collection.query(
            query_embeddings=[q_embedding],
            n_results=n_results,
            include=["documents", "metadatas", "distances"],
        )

        context_chunks = results["documents"][0] if results["documents"] else []
        metadatas = results["metadatas"][0] if results["metadatas"] else []
        distances = results["distances"][0] if results["distances"] else []

        # Check how many retrieved chunks are from relevant vs irrelevant docs
        relevant_retrieved = sum(1 for m in metadatas if m.get("relevant") == "True")
        irrelevant_retrieved = sum(1 for m in metadatas if m.get("relevant") == "False")

        # Build context
        context = "\n\n---\n\n".join(context_chunks)
        prompt = f"Context:\n{context}\n\n---\n\nQuestion: {question}\n\nAnswer:"

        answer = self.respond_stateless(prompt)

        return {
            "question": question,
            "answer": answer,
            "relevant_chunks_retrieved": relevant_retrieved,
            "irrelevant_chunks_retrieved": irrelevant_retrieved,
            "total_chunks_retrieved": len(context_chunks),
            "avg_distance": round(sum(distances) / max(len(distances), 1), 4),
        }


# ─── Accuracy Evaluator ─────────────────────────────────────────────────────

def evaluate_answer(llm: OllamaLLM, question: str, answer: str, expected: str) -> dict:
    """Use the LLM as a judge to evaluate answer quality."""
    prompt = f"""You are an expert evaluator. Rate the following answer on a scale of 0-10.

Question: {question}
Expected Answer: {expected}
Actual Answer: {answer}

Respond with ONLY a JSON object:
{{"score": <0-10>, "explanation": "brief reason"}}"""

    resp = llm.generate(prompt, json_mode=True, temperature=0.1)
    try:
        result = json.loads(resp.content)
        return {"score": result.get("score", 0), "explanation": result.get("explanation", "")}
    except (json.JSONDecodeError, AttributeError):
        return {"score": 0, "explanation": "Failed to parse evaluation"}


# ─── Main Experiment Runner ──────────────────────────────────────────────────

def run_experiment(use_archivist: bool = False, run_label: str = ""):
    """
    Run one instance of the experiment.
    
    Args:
        use_archivist: If True, run the Archivist Agent before the Decision phase.
        run_label: Label for this run (e.g., 'control' or 'with_archivist').
    """
    label = run_label or ("with_archivist" if use_archivist else "control")
    logger = ExperimentLogger("exp1_memory_pollution", run_id=label)

    logger.log_event("info", message=f"{'='*60}")
    logger.log_event("info", message=f"EXPERIMENT 1: Memory Pollution — {label.upper()}")
    logger.log_event("info", message=f"Archivist: {'ENABLED' if use_archivist else 'DISABLED'}")
    logger.log_event("info", message=f"{'='*60}")

    # Initialize embedding model
    logger.log_event("info", message="Loading sentence-transformers embedding model...")
    embedder = SentenceTransformer("all-MiniLM-L6-v2")

    # Initialize ChromaDB
    chroma_client = chromadb.Client()  # in-memory for clean experiments
    collection_name = f"exp1_{label}_{int(time.time())}"
    collection = chroma_client.create_collection(
        name=collection_name,
        metadata={"hnsw:space": "cosine"},
    )
    logger.log_event("info", message=f"Created ChromaDB collection: {collection_name}")

    # Initialize LLMs
    gen_llm = OllamaLLM(model=FAST_MODEL, temperature=0.7)
    eval_llm = OllamaLLM(model=FAST_MODEL, temperature=0.1)

    # ─── Phase 1: Generate / Load Documents ──────────────────────────────
    relevant_docs, irrelevant_docs = generate_synthetic_documents(gen_llm, logger)
    all_docs = relevant_docs + irrelevant_docs

    logger.log_metric("total_documents", len(all_docs))
    logger.log_metric("relevant_documents", len(relevant_docs))
    logger.log_metric("irrelevant_documents", len(irrelevant_docs))

    # ─── Phase 2: Research Agents Ingest ─────────────────────────────────
    research_agents = [
        ResearchAgent(f"Researcher_{i+1}", FAST_MODEL, collection, embedder, logger)
        for i in range(3)
    ]

    # Distribute docs among researchers, tracking DB growth over time
    db_size_timeline = []
    for i, doc in enumerate(all_docs):
        agent = research_agents[i % 3]
        agent.ingest_documents([doc])
        # Track DB growth every 5 docs
        if (i + 1) % 5 == 0 or i == len(all_docs) - 1:
            current_size = collection.count()
            db_size_timeline.append({"doc_index": i + 1, "db_chunks": current_size})
            logger.log_metric("db_size_timeline", {"doc_index": i + 1, "chunks": current_size})

    db_size_before = collection.count()
    logger.log_metric("db_size_after_ingestion", db_size_before)
    logger.log_metric("db_growth_timeline", db_size_timeline)

    # ─── Phase 3 (Variable): Archivist Prunes ───────────────────────────
    archivist_stats = {}
    if use_archivist:
        archivist = ArchivistAgent(FAST_MODEL, collection, embedder, logger)
        archivist_stats = archivist.audit_and_prune()
        logger.log_metric("db_size_after_archivist", collection.count())

    # ─── Phase 4: Decision Agent Answers Questions ───────────────────────
    questions = generate_evaluation_questions(gen_llm, logger)
    decision_agent = DecisionAgent(FAST_MODEL, collection, embedder, logger)

    results = []
    for q in questions:
        answer_data = decision_agent.answer_question(q["question"])
        eval_result = evaluate_answer(eval_llm, q["question"], answer_data["answer"], q["expected_answer"])
        answer_data["eval_score"] = eval_result["score"]
        answer_data["eval_explanation"] = eval_result["explanation"]
        results.append(answer_data)

        logger.log_event(
            "info", agent="DecisionMaker",
            data=answer_data,
            message=f"Q: {q['question'][:60]}... → Score: {eval_result['score']}/10",
        )

    # ─── Phase 5: Compile Metrics ────────────────────────────────────────
    avg_score = sum(r["eval_score"] for r in results) / max(len(results), 1)
    avg_relevant = sum(r["relevant_chunks_retrieved"] for r in results) / max(len(results), 1)
    avg_irrelevant = sum(r["irrelevant_chunks_retrieved"] for r in results) / max(len(results), 1)
    total_tokens = sum(a.total_tokens_used for a in research_agents) + decision_agent.total_tokens_used

    metrics = {
        "condition": label,
        "archivist_enabled": use_archivist,
        "avg_accuracy_score": round(avg_score, 2),
        "avg_relevant_chunks_retrieved": round(avg_relevant, 2),
        "avg_irrelevant_chunks_retrieved": round(avg_irrelevant, 2),
        "retrieval_precision": round(avg_relevant / max(avg_relevant + avg_irrelevant, 1), 3),
        "db_size_final": collection.count(),
        "db_size_before_archivist": db_size_before,
        "db_growth_timeline": db_size_timeline,
        "archivist_stats": archivist_stats,
        "total_tokens_used": total_tokens,
    }

    logger.summary_table(metrics)
    logger.log_metric("final_metrics", metrics)

    # Save results
    results_file = DATA_DIR / f"exp1_results_{label}.json"
    with open(results_file, "w") as f:
        json.dump({"metrics": metrics, "answers": results}, f, indent=2)

    logger.log_event("info", message=f"Results saved to {results_file}")
    logger.finalize()
    return metrics


def main():
    """Run both control and variable conditions."""
    print("\n" + "="*70)
    print("  NAIL INSTITUTE — EXPERIMENT 1: TRAGEDY OF THE COMMONS")
    print("  Memory Pollution in Shared Multi-Agent Knowledge Bases")
    print("="*70 + "\n")

    # Run control (no archivist)
    control_metrics = run_experiment(use_archivist=False, run_label="control")

    print("\n" + "-"*70 + "\n")

    # Run variable (with archivist)
    variable_metrics = run_experiment(use_archivist=True, run_label="with_archivist")

    # ─── Comparison ──────────────────────────────────────────────────────
    print("\n" + "="*70)
    print("  COMPARATIVE RESULTS")
    print("="*70)
    print(f"  Control Accuracy:   {control_metrics['avg_accuracy_score']}/10")
    print(f"  Archivist Accuracy: {variable_metrics['avg_accuracy_score']}/10")
    print(f"  Improvement:        {variable_metrics['avg_accuracy_score'] - control_metrics['avg_accuracy_score']:+.2f}")
    print(f"  Control Precision:  {control_metrics['retrieval_precision']}")
    print(f"  Archivist Precision:{variable_metrics['retrieval_precision']}")
    print("="*70)

    # Save comparison
    comparison_file = DATA_DIR / "exp1_comparison.json"
    with open(comparison_file, "w") as f:
        json.dump({
            "control": control_metrics,
            "with_archivist": variable_metrics,
            "accuracy_delta": variable_metrics["avg_accuracy_score"] - control_metrics["avg_accuracy_score"],
            "precision_delta": variable_metrics["retrieval_precision"] - control_metrics["retrieval_precision"],
        }, f, indent=2)
    print(f"\nComparison saved to {comparison_file}")


if __name__ == "__main__":
    main()
