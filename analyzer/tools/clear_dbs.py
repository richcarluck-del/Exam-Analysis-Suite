from app.graph_db import db as graph_db
from app.vector_db import db as vector_db

def clear_all_databases():
    """Clears both Neo4j and ChromaDB."""
    # Clear Neo4j
    try:
        print("Clearing Neo4j database...")
        graph_db.run_query("MATCH (n) DETACH DELETE n")
        print("Successfully cleared the Neo4j database.")
    except Exception as e:
        print(f"An error occurred while clearing Neo4j: {e}")
    finally:
        graph_db.close()

    # Clear ChromaDB
    try:
        print("Clearing ChromaDB collection...")
        vector_db.clear_collection()
        print("Successfully cleared the ChromaDB collection.")
    except Exception as e:
        print(f"An error occurred while clearing ChromaDB: {e}")

if __name__ == "__main__":
    clear_all_databases()