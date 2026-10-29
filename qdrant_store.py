from langchain_qdrant import QdrantVectorStore
from langchain_community.embeddings import FastEmbedEmbeddings
from qdrant_client import QdrantClient

def setup_vector_store():
    print("Initializing local Qdrant client...")
    
    # Connect to local Qdrant instance running via Docker
    client = QdrantClient(host="localhost", port=6333)
    
    # Collection name for LogLens error knowledge base
    collection_name = "loglens_kb"
    
    # Use lightweight local FastEmbed (no PyTorch/cloud API needed!)
    embeddings = FastEmbedEmbeddings(model_name="BAAI/bge-small-en-v1.5")
    
    # Sample historical errors & solutions to seed our vector database
    sample_knowledge = [
        "Error: NullPointerException in UserRepository.save() because userRepository is null. Fix: Ensure the service class uses @Autowired or proper dependency injection to initialize the repository bean.",
        "Error: Connection refused to PostgreSQL on port 5432. Fix: Check if the database container is running and verify DB_HOST and DB_PORT environment variables.",
        "Error: OutOfMemoryError: Java heap space. Fix: Increase the JVM maximum heap size using the -Xmx flag, e.g., java -Xmx2g -jar app.jar."
    ]
    
    metadata = [
        {"source": "spring_boot_docs", "error_type": "NullPointerException"},
        {"source": "db_troubleshooting", "error_type": "ConnectionRefused"},
        {"source": "jvm_tuning", "error_type": "OutOfMemoryError"}
    ]

    print("Embedding and storing knowledge base into Qdrant...")
    
    # Use QdrantVectorStore from the official langchain-qdrant package
    vector_store = QdrantVectorStore.from_texts(
        texts=sample_knowledge,
        embedding=embeddings,
        metadatas=metadata,
        url="http://localhost:6333",
        collection_name=collection_name
    )
    
    print("Successfully stored documents in Qdrant!")
    return vector_store, embeddings

if __name__ == "__main__":
    store, emb = setup_vector_store()
    
    query = "Why am I getting a null pointer exception when trying to save a user?"
    print(f"\nSearching Qdrant for query: '{query}'\n")
    
    results = store.similarity_search(query, k=1)
    for res in results:
        print(f"--- Found Match (Source: {res.metadata['source']}) ---")
        print(res.page_content)
