import argparse
import sys
import re
from qdrant_client import QdrantClient
from langchain_community.embeddings import FastEmbedEmbeddings
from langchain_qdrant import QdrantVectorStore
from langchain_core.documents import Document
import ollama

class LogSanitizer:
    """Handles local PII and secret scrubbing from raw error logs."""
    def __init__(self):
        self.patterns = {
            "api_key": r"(api[_-]?key|secret|token|auth)[=:\s]+['\"]?([a-zA-Z0-9_\-]{20,})['\"]?",
            "bearer_token": r"Bearer\s+[a-zA-Z0-9_\-\.]+",
            "ip_address": r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b",
            "email": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
            "password": r"(password|passwd|pwd)[=:\s]+['\"]?([^\s'\"]+)['\"]?"
        }

    def sanitize(self, log_text: str) -> str:
        sanitized = log_text
        sanitized = re.sub(self.patterns["api_key"], r"\1=[REDACTED]", sanitized, flags=re.IGNORECASE)
        sanitized = re.sub(self.patterns["bearer_token"], "Bearer [REDACTED]", sanitized, flags=re.IGNORECASE)
        sanitized = re.sub(self.patterns["password"], r"\1=[REDACTED]", sanitized, flags=re.IGNORECASE)
        sanitized = re.sub(self.patterns["email"], "[EMAIL_REDACTED]", sanitized)
        sanitized = re.sub(self.patterns["ip_address"], "[IP_REDACTED]", sanitized)
        return sanitized


def get_official_doc_portal(tech_stack: str, query: str) -> str:
    """Dynamically maps detected technology to its verified official documentation search portal."""
    tech = tech_stack.lower()
    encoded_query = query.replace(" ", "+")
    
    # Official root documentation portals mapped by technology domain
    if "redis" in tech:
        return f"https://redis.io/search?q={encoded_query}"
    elif "postgres" in tech or "sql" in tech:
        return f"https://www.postgresql.org/search/?q={encoded_query}"
    elif "java" in tech or "spring" in tech:
        return f"https://docs.oracle.com/en/search/?q={encoded_query}"
    elif "kafka" in tech:
        return f"https://kafka.apache.org/documentation/#search"
    elif "docker" in tech or "container" in tech:
        return f"https://docs.docker.com/search/?q={encoded_query}"
    elif "python" in tech:
        return f"https://docs.python.org/3/search.html?q={encoded_query}"
    else:
        # Fallback to general tech search portal if custom stack
        return f"https://stackoverflow.com/search?q={encoded_query}"


def run_cli_pipeline(raw_log: str):
    """Executes the complete LogLens autonomous RAG and Active Learning pipeline."""
    print("🔍 [1/4] Sanitizing log locally...")
    sanitizer = LogSanitizer()
    clean_log = sanitizer.sanitize(raw_log)
    print(f"   -> Cleaned: {clean_log}\n")

    print("🧠 [2/4] Querying Qdrant knowledge base...")
    try:
        client = QdrantClient(host="localhost", port=6333)
        embeddings = FastEmbedEmbeddings(model_name="BAAI/bge-small-en-v1.5")
        vector_store = QdrantVectorStore(
            client=client,
            collection_name="loglens_kb",
            embedding=embeddings
        )
        
        results = vector_store.similarity_search_with_score(clean_log, k=1)
    except Exception as e:
        print(f"   -> Warning: Could not connect to Qdrant ({e}). Proceeding without history.")
        results = []

    context = ""
    error_type = "CustomError"
    stored_doc_url = ""
    is_learned_match = False

    if results:
        doc, score = results[0]
        print(f"   -> Best match found with distance score: {score:.4f}")
        if score < 0.6:
            context = doc.page_content
            error_type = doc.metadata.get("error_type", "CustomError")
            stored_doc_url = doc.metadata.get("official_doc", "")
            is_learned_match = True
            print(f"   -> High confidence match from memory! Error Type: {error_type}\n")
        else:
            print("   -> Match score too low. Treating as a new/unknown error.\n")
    else:
        print("   -> No historical match found in vector store.\n")

    print("🤖 [3/4] Generating dynamic diagnosis with local Ollama (llama3.2)...")
    prompt = f"""
    You are an expert DevOps and Backend Platform Engineer. Analyze the following sanitized error log using the provided historical context.

    HISTORICAL CONTEXT / KNOWN FIX:
    {context if context else "No direct historical match found. Analyze based on standard platform engineering practices."}

    INCOMING ERROR LOG:
    {clean_log}

    Provide your response strictly in the following format:
    1. ERROR_KEYWORD: (A short camelCase category name for this error, e.g., RedisTimeout, DatabaseConnectionRefused, NullPointerException)
    2. TECH_STACK: (The underlying technology or platform, e.g., redis, postgresql, java, kafka, docker, python)
    3. ROOT CAUSE: (Short description of why it failed)
    4. SEVERITY: (CRITICAL / HIGH / MEDIUM / LOW)
    5. RECOMMENDED FIX: (Actionable steps or code change needed)
    6. SEARCH_QUERY: (A targeted search query string to find documentation for this specific error)
    """

    try:
        response = ollama.chat(
            model='llama3.2',
            messages=[{'role': 'user', 'content': prompt}]
        )
        analysis = response['message']['content']
    except Exception as e:
        analysis = f"1. ERROR_KEYWORD: OllamaError\n2. TECH_STACK: general\n3. ROOT CAUSE: Error communicating with local Ollama service.\n4. SEVERITY: HIGH\n5. RECOMMENDED FIX: Ensure Ollama is running (`ollama serve`). Details: {e}\n6. SEARCH_QUERY: debugging local llm service error"

    detected_error_type = error_type
    tech_stack = "general"
    search_query = "error troubleshooting guide"
    
    for line in analysis.split('\n'):
        if "ERROR_KEYWORD:" in line:
            detected_error_type = line.replace("ERROR_KEYWORD:", "").strip()
        elif "TECH_STACK:" in line:
            tech_stack = line.replace("TECH_STACK:", "").strip()
        elif "SEARCH_QUERY:" in line:
            raw_query = line.replace("SEARCH_QUERY:", "").strip().strip('"')
            search_query = re.sub(r'^\d+[\.\)]\s*', '', raw_query)

    if is_learned_match and stored_doc_url:
        official_doc_url = stored_doc_url
    else:
        official_doc_url = get_official_doc_portal(tech_stack, search_query)

    if not is_learned_match:
        print(f"💡 [4/4] Active Learning: Auto-storing new error signature '{detected_error_type}' into Qdrant...")
        try:
            new_doc = Document(
                page_content=clean_log,
                metadata={
                    "error_type": detected_error_type, 
                    "solution": analysis,
                    "official_doc": official_doc_url
                }
            )
            vector_store.add_documents([new_doc])
            print("   -> Successfully saved new error pattern and official documentation portal to Qdrant!\n")
        except Exception as e:
            print(f"   -> Could not auto-store to Qdrant: {e}\n")

    official_link_output = f"""
6. OFFICIAL DOCUMENTATION PORTAL:
   - Official Docs Search: {official_doc_url}
"""

    return analysis + "\n" + official_link_output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="LogLens: Open-source AI log diagnosis and learning tool.")
    parser.add_argument("--log", type=str, help="Raw error log string to analyze.")
    parser.add_argument("--file", type=str, help="Path to a log file to analyze.")
    
    args = parser.parse_args()

    log_content = ""
    if args.log:
        log_content = args.log
    elif args.file:
        try:
            with open(args.file, "r") as f:
                log_content = f.read()
        except Exception as e:
            print(f"Error reading file: {e}")
            sys.exit(1)
    else:
        log_content = '2026-10-30 08:30:00 ERROR [main] UserService : Failed with password=Secret123 java.lang.NullPointerException'

    print("=== STARTING LOGLENS CLI DIAGNOSIS ===")
    report = run_cli_pipeline(log_content)
    print("\n=== FINAL REPORT ===")
    print(report)
