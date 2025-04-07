# utils/mongo_config.py
import os
from pymongo import MongoClient
from dotenv import load_dotenv
import logging

# Load environment variables from .env file
load_dotenv()

# Setup log and mongodb
MONGO_URI = os.environ.get("MONGO_URI")
logger = logging.getLogger(__name__)

# Create a global MongoDB client with connection pooling
try:
    MONGO_CLIENT = MongoClient(
        MONGO_URI,
        maxPoolSize=100,  # Maximum connections in the pool
        minPoolSize=10,   # Minimum connections to maintain
        maxIdleTimeMS=30000,  # Max idle time before closing (30 seconds)
        connectTimeoutMS=5000,  # Connection timeout
        serverSelectionTimeoutMS=5000  # Server selection timeout
    )
    # Verify connection on startup
    MONGO_CLIENT.admin.command('ping')
    logger.info("Connected successfully to MongoDB")
except Exception as e:
    logger.error(f"Error connecting to MongoDB: {e}")
    MONGO_CLIENT = None

def get_mongodb_connection():
    """
    Return the global MongoDB client connection.
    
    Returns:
        MongoClient or None: MongoDB client if connection successful, None otherwise
    """
    return MONGO_CLIENT

def get_collection(database_name, collection_name):
    """
    Get a specific collection from MongoDB.
    
    Args:
        database_name (str): Name of the database
        collection_name (str): Name of the collection
        
    Returns:
        Collection or None: MongoDB collection if connection successful, None otherwise
    """
    if MONGO_CLIENT:
        return MONGO_CLIENT[database_name][collection_name]
    return None

def close_mongodb_connection():
    """
    Close the MongoDB client connection - should only be called when the application shuts down.
    """
    if MONGO_CLIENT:
        MONGO_CLIENT.close()
        logger.info("MongoDB connection closed")