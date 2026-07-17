import os
import weaviate
from weaviate.classes.init import Auth
from weaviate.classes.config import Configure, Property, DataType
from weaviate.exceptions import WeaviateQueryError, WeaviateConnectionError
from weaviate.classes.query import Filter


# Weaviate Configuration from environment variables


def connect_to_weaviate():
    """Connects to Weaviate and returns the client object."""

    try:
        WEAVIATE_URL = os.getenv("WEAVIATE_URL")
        WEAVIATE_API_KEY = os.getenv("WEAVIATE_API_KEY")
        if not WEAVIATE_URL or not WEAVIATE_API_KEY:
            print("unable to fetch weaviate api/url")
            return None
        print("Connecting to Weaviate Cloud...")
        client = weaviate.connect_to_weaviate_cloud(
            cluster_url=WEAVIATE_URL,
            auth_credentials=Auth.api_key(WEAVIATE_API_KEY),
            skip_init_checks=True
        )
        if not client.is_ready():
            print("❌ Could not connect to Weaviate. Check your credentials.")
            return None
        print("✅ Weaviate connection successful.")
        return client
    except WeaviateConnectionError as e:
        print(f"❌ Weaviate connection error: {e}")
        return None

#collection creation
def get_or_create_collection(client, collection_name="VIT_docs", fresh_start=False):
    """
    Gets or creates a Weaviate collection. 
    If fresh_start is True, it will delete the collection if it already exists.
    """
    if fresh_start and client.collections.exists(collection_name):
        print(f"Deleting existing collection '{collection_name}'...")
        client.collections.delete(collection_name)

    if not client.collections.exists(collection_name):
        print(f"Collection '{collection_name}' not found. Creating...")
        try:
            client.collections.create(
                name=collection_name,
                vector_config=Configure.Vectors.text2vec_weaviate(),
                properties=[
                    Property(name="text_chunk", data_type=DataType.TEXT),
                    Property(name="source_file", data_type=DataType.TEXT)
                ],
            )
            print(f"✅ Collection '{collection_name}' created.")
        except Exception as e:
            print(f"❌ Error creating collection: {e}")
            return None
    else:
        print(f"Collection '{collection_name}' already exists.")
    
    return client.collections.get(collection_name)

#ingesting data into the collection
def ingest_data(collection, data_objects):
    """Ingests a list of data objects into the specified collection."""
    if not data_objects:
        print("Warning: No data provided for ingestion.")
        return
    
    print(f"Ingesting {len(data_objects)} objects into '{collection.name}'...")
    try:
        with collection.batch.dynamic() as batch:
            for obj in data_objects:
                batch.add_object(properties=obj)
        print("✅ Data ingestion successful.")
    except Exception as e:
        print(f"❌ Error during data ingestion: {e}")


# retrieving chunks through similarity search from weaviate
def retrieve_chunks(collection, query_text, limit=3):
    """Retrieves relevant text chunks from the Weaviate collection."""
    try:
        print("Retrieving relevant documents from Weaviate...")
        response = collection.query.near_text(
            query=query_text,
            limit=limit
        )
        
        retrieved_chunks = []
        if response.objects:
             retrieved_chunks = [obj.properties['text_chunk'] for obj in response.objects]
        
        if not retrieved_chunks:
            print("No relevant documents found in Weaviate for your query.")
            return []
        
        print(f"✅ Retrieved {len(retrieved_chunks)} document(s):")
        for i, chunk in enumerate(retrieved_chunks):
            print(f"  - Chunk {i+1}: {chunk[:100]}...") # Print a snippet
        return retrieved_chunks

    except WeaviateQueryError as e:
        print(f"❌ Weaviate query error: {e}")
        return []
    
#deletion function to replace outdated documents whenever required
def delete_chunks_from_source(collection, source_filename):
    """Deletes all chunks associated with a specific source file from the collection."""
    if not source_filename:
        print("Warning: No source filename provided for deletion.")
        return

    print(f"Attempting to delete all chunks from source: '{source_filename}'...")
    try:
        # Use a 'where' filter to target objects by their 'source_file' property
        response = collection.data.delete_many(
            where=Filter.by_property("source_file").equal(source_filename)
        )
        
        # The response object contains information about the operation
        print(f"✅ Deletion successful. Matched {response.matched_count} and deleted {response.successful_count} object(s).")
        if response.failed_count > 0:
            print(f"⚠️ Failed to delete {response.failed_count} object(s). Errors: {response.errors}")

    except Exception as e:
        print(f"❌ An error occurred during deletion: {e}")


