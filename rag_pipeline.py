import re
import json
from qdrant_client import QdrantClient
from langchain_community.embeddings import FastEmbedEmbeddings
from langchain_qdrant import QdrantVectorStore
import ollama

class LogSanitizer:
    def __init__(self):
        self.patterns = {
            "api_key": r"(api[_-]?key|secret|token|auth)[=:\s]+['\"]?([a-zA-Z0-9_\-]{20,})['\"]?",
            "bearer_token": r"Bearer\s+[a-zA-Z0-9_\-\.]+",
            "ip_address": r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b",
            "email": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
            "password": r"(password|passwd|pwd)[=:\s]+['\"]?([^\s'\"]+)['\"]?"
        }

    def sanitize(self, log_text: str) -> str:
        """Scrub sensitive data locally before analysis."""
        sanitized = log_text
        sanitized = re.sub(self.patterns["api_key"], r"\1=[REDACTED]", sanitized, flags=re.IGNORECASE)
        sanitized = re.sub(self.patterns["bearer_token"], "Bearer [REDACTED]", sanitized, flags=re.IGNORECASE)
        sanitized = re.sub(self.patterns["password"], r"\1=[REDACTED]", sanitized, flags=re.IGNORECASE)
        sanitized = re.sub(self.patterns["email"], "[EMAIL_REDACTED]", sanitized)
        sanitized = re.sub(self.patterns["ip_address"], "[IP_REDACTED]", sanitized)
        return sanitized


def run_rag_pipeline(raw_log: str):
    print("Step 1: Sanitizing log locally...")
    sanitizer = LogSanitizer()
    clean_log = sanitizer.sanitize(raw_log)
    print(f"Sanitized Log:\n{clean_log}\n")

    print("Step 2: Connecting to Qdrant & searching for similar historical errors...")
    client = QdrantClient(host="localhost", port=6333)
    embeddings = FastEmbedEmbeddings(model_name="BAAI/bge-small-en-v1.5")
    
    vector_store = QdrantVectorStore(
        client=client,
        collection_name="loglens_kb",
        embedding=embeddings
    )

    # Perform similarity search to retrieve relevant context
    retrieved_docs = vector_store.similarity_search(clean_log, k=1)
    
    context = ""
    if retrieved_docs:
        context = retrieved_docs[0].page_content
        print(f"Retrieved Context from Qdrant: {context}\n")
    else:
        print("No historical context found in vector store. Proceeding with LLM base knowledge.\n")

    print("Step 3: Constructing RAG prompt & querying local Ollama (llama3.2)...")
    prompt = f"""
    You are an expert DevOps and Backend Platform Engineer. Analyze the following sanitized error log using the provided historical context.

    HISTORICAL CONTEXT / KNOWN FIX:
    {context if context else "No direct historical match found."}

    INCOMING ERROR LOG:
    {clean_log}

    Provide your response strictly in the following structured format:
    1. ROOT CAUSE: (Short description of why it failed)
    2. SEVERITY: (CRITICAL / HIGH / MEDIUM / LOW)
    3. RECOMMENDED FIX: (Actionable steps or code change needed based on context)
    """

    response = ollama.chat(
        model='llama3.2',
        messages=[{'role': 'user', 'content': prompt}]
    )

    return response['message']['content']


if __name__ == "__main__":
    # Test sample log containing secrets & a known error
    incoming_error = '2026-10-30 08:30:00 ERROR [main] c.m.p.s.UserService : Failed registration with password=SecretPassword999 java.lang.NullPointerException: Cannot invoke UserRepository.save()'
    
    print("=== STARTING LOGLENS RAG DIAGNOSIS ===")
    analysis = run_rag_pipeline(incoming_error)
    
    print("\n=== LOGLENS AI ANALYSIS ===")
    print(analysis)
