"""RAG pipeline for the PubMed chatbot.

This file contains the chatbot logic, not the UI.

The main function for the UI is run_rag_pipeline(question, memory_manager).
It:
1. Retrieves the top 5 PubMed chunks.
2. Retrieves short-term and long-term conversation memory.
3. Builds the final prompt.
4. Creates a simple context-grounded answer.
5. Saves the user question and assistant answer to memory.

For now, the answer generator is intentionally simple and local. It does not
call an external LLM. It builds an answer only from retrieved PubMed text, which
keeps the project runnable without API keys.
"""

from __future__ import annotations

import argparse
import os
import re
from typing import Any

try:
    from src.memory_manager import ChatMemoryManager, default_memory_manager
    from src.retriever import retrieve_similar_chunks
except ModuleNotFoundError:  # Allows: python src/rag_chain.py
    from memory_manager import ChatMemoryManager, default_memory_manager  # type: ignore
    from retriever import retrieve_similar_chunks  # type: ignore


NOT_ENOUGH_INFORMATION_MESSAGE = (
    "The dataset does not contain enough information to answer this question."
)

# If the best retrieved chunk is below this score, the answer is considered too
# weak to trust. You can tune it from .env if needed.
MIN_RETRIEVAL_SCORE = float(os.getenv("MIN_RETRIEVAL_SCORE", "0.15"))
ENABLE_DOMAIN_GUARD = os.getenv("ENABLE_DOMAIN_GUARD", "true").lower() == "true"

STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "how",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "this",
    "to",
    "was",
    "were",
    "what",
    "when",
    "where",
    "which",
    "with",
}

MEDICAL_KEYWORDS = {
    "abstract",
    "analgesic",
    "analgesics",
    "anatomy",
    "antibody",
    "asthma",
    "bacteria",
    "biochemical",
    "biomarker",
    "blood",
    "breast",
    "cancer",
    "cardiac",
    "cardiovascular",
    "cell",
    "cells",
    "cervical",
    "chemotherapy",
    "clinical",
    "deficiency",
    "depression",
    "diabetes",
    "diagnosis",
    "disease",
    "diseases",
    "dna",
    "dose",
    "drug",
    "enzyme",
    "gene",
    "genetic",
    "genomic",
    "health",
    "heart",
    "hpv",
    "human",
    "humans",
    "hypovitaminosis",
    "immunology",
    "infant",
    "infection",
    "inflammation",
    "kidney",
    "lactation",
    "medical",
    "medicine",
    "mesh",
    "mice",
    "molecular",
    "mother",
    "neonatal",
    "neoplasm",
    "neoplasms",
    "obesity",
    "opioid",
    "pain",
    "parathormone",
    "patient",
    "patients",
    "peptide",
    "peptides",
    "p53",
    "pharmacology",
    "pregnancy",
    "pregnant",
    "protein",
    "pubmed",
    "receptor",
    "receptors",
    "serum",
    "study",
    "syndrome",
    "therapy",
    "tissue",
    "treatment",
    "tumor",
    "tyr-pro",
    "viral",
    "virus",
    "vitamin",
}

MEDICAL_PHRASES = {
    "cervical cancer",
    "vitamin d",
    "pubmed abstract",
    "medical abstract",
    "opioid peptide",
    "p53 expression",
}

NON_MEDICAL_KEYWORDS = {
    "bake",
    "cake",
    "chocolate",
    "cooking",
    "recipe",
    "football",
    "capital",
    "programming",
    "game",
    "movie",
    "travel",
    "restaurant",
}


def tokenize_question(question: str) -> set[str]:
    """Convert a question into simple lowercase keyword tokens."""

    return set(re.findall(r"[a-zA-Z][a-zA-Z0-9-]+", question.lower()))


def is_medical_or_pubmed_question(question: str) -> bool:
    """Quickly decide if a question belongs in this PubMed chatbot.

    This guard is intentionally lightweight. It prevents obviously unrelated
    questions, such as recipes, from loading the embedding model and scanning
    MongoDB.
    """

    if not ENABLE_DOMAIN_GUARD:
        return True

    question_lower = question.lower()
    tokens = tokenize_question(question)

    if any(phrase in question_lower for phrase in MEDICAL_PHRASES):
        return True

    if tokens & MEDICAL_KEYWORDS:
        return True

    # If a question only contains obvious non-medical words, reject it quickly.
    if tokens & NON_MEDICAL_KEYWORDS:
        return False

    # Unknown topics are rejected by default so the app stays focused on the
    # ingested PubMed dataset.
    return False


def build_dataset_context(chunks: list[dict[str, Any]]) -> str:
    """Turn retrieved PubMed chunks into a numbered context block."""

    if not chunks:
        return "No relevant context was retrieved from the dataset."

    context_parts = []

    for index, chunk in enumerate(chunks, start=1):
        metadata = chunk.get("metadata", {})
        title = metadata.get("title") or "Unknown title"
        pmid = metadata.get("pmid") or "Unknown PMID"
        score = chunk.get("score", 0.0)
        text = chunk.get("text", "")

        context_parts.append(
            f"[Context Chunk {index}]\n"
            f"Similarity score: {score:.4f}\n"
            f"PMID: {pmid}\n"
            f"Title: {title}\n"
            f"Text: {text}"
        )

    return "\n\n".join(context_parts)


def build_short_term_memory_context(messages: list[dict[str, str]]) -> str:
    """Format the last 20 conversation messages for the prompt."""

    if not messages:
        return "No recent conversation messages in this session."

    formatted_messages = []
    for index, message in enumerate(messages, start=1):
        role = message.get("role", "unknown")
        content = message.get("content", "")
        formatted_messages.append(f"{index}. {role}: {content}")

    return "\n".join(formatted_messages)


def build_long_term_memory_context(memories: list[dict[str, Any]]) -> str:
    """Format relevant older MongoDB memory messages for the prompt."""

    if not memories:
        return "No relevant older memory messages were found."

    formatted_memories = []
    for index, memory in enumerate(memories, start=1):
        role = memory.get("role", "unknown")
        content = memory.get("content", "")
        score = memory.get("score", 0.0)
        created_at = memory.get("created_at")

        formatted_memories.append(
            f"{index}. role: {role}\n"
            f"   similarity score: {score:.4f}\n"
            f"   created at: {created_at}\n"
            f"   content: {content}"
        )

    return "\n".join(formatted_memories)


def build_prompt(
    question: str,
    chunks: list[dict[str, Any]],
    short_term_messages: list[dict[str, str]],
    long_term_memories: list[dict[str, Any]],
) -> str:
    """Build the final RAG prompt from dataset chunks and memory."""

    dataset_context = build_dataset_context(chunks)
    short_term_context = build_short_term_memory_context(short_term_messages)
    long_term_context = build_long_term_memory_context(long_term_memories)

    return f"""You are a medical literature assistant.

Answer the user question using only the context provided below.
Do not use outside knowledge.
Use the PubMed dataset context as the source for medical facts.
Use conversation memory only to understand the user's prior messages and preferences.
If the answer is not found in the PubMed dataset context, say:
"{NOT_ENOUGH_INFORMATION_MESSAGE}"

PubMed dataset context:
{dataset_context}

Recent conversation memory - last 20 messages:
{short_term_context}

Relevant older conversation memory:
{long_term_context}

User question:
{question}

Answer:"""


def get_question_keywords(question: str) -> set[str]:
    """Extract simple keywords from the user's question."""

    words = re.findall(r"[a-zA-Z][a-zA-Z0-9-]+", question.lower())
    return {
        word
        for word in words
        if len(word) > 2 and word not in STOPWORDS
    }


def split_into_sentences(text: str) -> list[str]:
    """Split text into sentences using a simple regex."""

    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    return [sentence.strip() for sentence in sentences if sentence.strip()]


def sentence_relevance_score(sentence: str, keywords: set[str]) -> int:
    """Score a sentence by how many question keywords it contains."""

    sentence_lower = sentence.lower()
    return sum(1 for keyword in keywords if keyword in sentence_lower)


def select_answer_sentences(
    question: str,
    chunks: list[dict[str, Any]],
    max_sentences: int = 5,
) -> list[str]:
    """Select the most relevant sentences from retrieved chunks."""

    keywords = get_question_keywords(question)
    candidates: list[tuple[float, int, str]] = []

    for chunk_index, chunk in enumerate(chunks):
        chunk_score = float(chunk.get("score", 0.0))
        if chunk_score < MIN_RETRIEVAL_SCORE:
            continue

        for sentence in split_into_sentences(chunk.get("text", "")):
            if len(sentence) < 20:
                continue

            keyword_score = sentence_relevance_score(sentence, keywords)
            combined_score = keyword_score + chunk_score
            candidates.append((combined_score, chunk_index, sentence))

    candidates.sort(key=lambda item: item[0], reverse=True)

    selected_sentences = []
    seen_sentences = set()

    for _, _, sentence in candidates:
        normalized = sentence.lower()
        if normalized in seen_sentences:
            continue

        selected_sentences.append(sentence)
        seen_sentences.add(normalized)

        if len(selected_sentences) >= max_sentences:
            break

    return selected_sentences


def generate_final_answer(
    question: str,
    chunks: list[dict[str, Any]],
) -> str:
    """Create a simple answer using only retrieved PubMed chunks.

    This is an extractive answer: it selects relevant sentences from the
    retrieved abstracts. A real LLM can be added later without changing the UI.
    """

    if not chunks:
        return NOT_ENOUGH_INFORMATION_MESSAGE

    best_score = float(chunks[0].get("score", 0.0))
    if best_score < MIN_RETRIEVAL_SCORE:
        return NOT_ENOUGH_INFORMATION_MESSAGE

    selected_sentences = select_answer_sentences(question, chunks)
    if not selected_sentences:
        return NOT_ENOUGH_INFORMATION_MESSAGE

    answer_lines = ["Based on the retrieved PubMed abstracts:"]
    for sentence in selected_sentences:
        answer_lines.append(f"- {sentence}")

    return "\n".join(answer_lines)


def remove_memories_already_in_short_term(
    memories: list[dict[str, Any]],
    short_term_messages: list[dict[str, str]],
) -> list[dict[str, Any]]:
    """Avoid showing the same message in both memory sections."""

    recent_pairs = {
        (message.get("role"), message.get("content"))
        for message in short_term_messages
    }

    filtered_memories = []
    for memory in memories:
        memory_pair = (memory.get("role"), memory.get("content"))
        if memory_pair not in recent_pairs:
            filtered_memories.append(memory)

    return filtered_memories


def run_rag_pipeline(
    question: str,
    memory_manager: ChatMemoryManager = default_memory_manager,
    save_to_memory: bool = True,
) -> dict[str, Any]:
    """Run the full RAG pipeline and return all data needed by the UI."""

    question = question.strip()
    if not question:
        raise ValueError("Question cannot be empty.")

    if not is_medical_or_pubmed_question(question):
        if save_to_memory:
            # Save out-of-domain messages only in short-term memory. They are
            # not useful for future medical retrieval, and skipping long-term
            # storage avoids embedding/MongoDB work for unrelated questions.
            memory_manager.add_message(
                "user",
                question,
                save_to_long_term=False,
            )

        short_term_for_prompt = memory_manager.get_short_term_messages()
        final_prompt = build_prompt(
            question=question,
            chunks=[],
            short_term_messages=short_term_for_prompt,
            long_term_memories=[],
        )
        final_answer = NOT_ENOUGH_INFORMATION_MESSAGE

        if save_to_memory:
            memory_manager.add_message(
                "assistant",
                final_answer,
                save_to_long_term=False,
            )

        return {
            "question": question,
            "answer": final_answer,
            "prompt": final_prompt,
            "dataset_chunks": [],
            "short_term_messages": short_term_for_prompt,
            "long_term_memories": [],
            "memory_after_answer": memory_manager.get_short_term_messages(),
            "skipped_retrieval": True,
            "skip_reason": "Question is outside the PubMed/medical domain.",
        }

    dataset_chunks = retrieve_similar_chunks(question, top_k=5)

    # Retrieve older memories before saving the current user question, so the
    # current question does not appear as its own older memory.
    short_term_before_question = memory_manager.get_short_term_messages()
    long_term_memories = memory_manager.retrieve_relevant_memories(
        question,
        top_k=5,
    )
    long_term_memories = remove_memories_already_in_short_term(
        long_term_memories,
        short_term_before_question,
    )

    if save_to_memory:
        memory_manager.add_user_message(question)

    short_term_for_prompt = memory_manager.get_short_term_messages()

    final_prompt = build_prompt(
        question=question,
        chunks=dataset_chunks,
        short_term_messages=short_term_for_prompt,
        long_term_memories=long_term_memories,
    )

    final_answer = generate_final_answer(question, dataset_chunks)

    if save_to_memory:
        memory_manager.add_assistant_message(final_answer)

    return {
        "question": question,
        "answer": final_answer,
        "prompt": final_prompt,
        "dataset_chunks": dataset_chunks,
        "short_term_messages": short_term_for_prompt,
        "long_term_memories": long_term_memories,
        "memory_after_answer": memory_manager.get_short_term_messages(),
        "skipped_retrieval": False,
        "skip_reason": None,
    }


def print_retrieved_chunks(chunks: list[dict[str, Any]]) -> None:
    """Print retrieved chunks in a readable format."""

    if not chunks:
        print("No retrieved chunks.")
        return

    for index, chunk in enumerate(chunks, start=1):
        metadata = chunk.get("metadata", {})
        print(f"\nRetrieved chunk {index}")
        print(f"Score: {chunk.get('score', 0.0):.4f}")
        print(f"PMID: {metadata.get('pmid')}")
        print(f"Title: {metadata.get('title')}")
        print(f"Text: {chunk.get('text', '')}")


def print_short_term_messages(messages: list[dict[str, str]]) -> None:
    """Print the current session's short-term memory."""

    if not messages:
        print("No short-term memory messages.")
        return

    for index, message in enumerate(messages, start=1):
        print(f"{index}. {message.get('role')}: {message.get('content')}")


def print_long_term_memories(memories: list[dict[str, Any]]) -> None:
    """Print retrieved long-term memory messages."""

    if not memories:
        print("No relevant older memory messages.")
        return

    for index, memory in enumerate(memories, start=1):
        print(f"\nMemory {index}")
        print(f"Score: {memory.get('score', 0.0):.4f}")
        print(f"Role: {memory.get('role')}")
        print(f"Created at: {memory.get('created_at')}")
        print(f"Content: {memory.get('content')}")


def answer_question(
    question: str,
    memory_manager: ChatMemoryManager = default_memory_manager,
) -> str:
    """Run the RAG pipeline, print debug output, and return the answer."""

    print("\nUser question")
    print("-------------")
    print(question)

    result = run_rag_pipeline(question, memory_manager=memory_manager)

    print("\nRetrieved chunks")
    print("----------------")
    print_retrieved_chunks(result["dataset_chunks"])

    print("\nShort-term memory")
    print("-----------------")
    print_short_term_messages(result["memory_after_answer"])

    print("\nRelevant older memory")
    print("---------------------")
    print_long_term_memories(result["long_term_memories"])

    print("\nFinal prompt")
    print("------------")
    print(result["prompt"])

    print("\nFinal answer")
    print("------------")
    print(result["answer"])

    return result["answer"]


def parse_args() -> argparse.Namespace:
    """Read the question from the command line."""

    parser = argparse.ArgumentParser(description="Run the PubMed RAG pipeline.")
    parser.add_argument("question", help="Question to answer.")
    return parser.parse_args()


def main() -> None:
    """Command line entry point for testing the RAG pipeline."""

    args = parse_args()
    answer_question(args.question)


if __name__ == "__main__":
    main()
