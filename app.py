import os
import requests
from flask import Flask, request, jsonify
from pymongo import MongoClient
from datetime import datetime
import ssl

app = Flask(__name__)

# MongoDB connection setup with TLS/SSL fix
def get_mongodb_connection():
    try:
        # Modified connection string with TLS configuration
        mongodb_uri = "mongodb+srv://li102677:BMILcEhbebhm5s1C@cluster0.aprrt.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"
        
        # Create a MongoDB client with specific TLS/SSL settings
        client = MongoClient(
            mongodb_uri,
            ssl=True,
            ssl_cert_reqs=ssl.CERT_NONE,  # Less secure but helps bypass certain TLS issues
            connectTimeoutMS=30000,
            socketTimeoutMS=30000,
            serverSelectionTimeoutMS=30000
        )
        
        # Test the connection with a simple command
        db_info = client.server_info()
        print(f"Connected to MongoDB: {db_info.get('version', 'unknown version')}")
        return client
    except Exception as e:
        print(f"MongoDB connection error: {e}")
        return None

@app.route('/')
def hello_world():
    try:
        # Connect to MongoDB when request comes to "/"
        client = get_mongodb_connection()
        
        if client:
            # Access the freq_questions database
            db = client.get_database("freq_questions")
            
            # Get collection names to verify connection
            try:
                collection_names = db.list_collection_names()
            except Exception as e:
                collection_names = ["Error listing collections: " + str(e)]
            
            # Record the connection in a collection
            try:
                connections = db.get_collection("connections")
                connection_record = {
                    "timestamp": datetime.now(),
                    "status": "connected"
                }
                connections.insert_one(connection_record)
            except Exception as e:
                print(f"Error inserting record: {e}")
            
            return jsonify({
                "text": "Hello from Koyeb - you reached the main page!",
                "mongodb_status": "connected",
                "collections": collection_names
            })
        else:
            return jsonify({
                "text": "Hello from Koyeb - you reached the main page!",
                "mongodb_status": "error",
                "error": "Failed to connect to MongoDB"
            })
            
    except Exception as e:
        return jsonify({
            "text": "Hello from Koyeb - you reached the main page!",
            "mongodb_status": "error",
            "error": str(e)
        })

@app.route('/query', methods=['POST'])
def main():
    data = request.get_json() 

    # Extract relevant information
    channel_id = data.get("channel_id", "unknown_channel")
    user_name = data.get("user_name", "Unknown")
    message = data.get("text", "")

    print(f"Received request: {data}")

    # Ignore bot messages
    if data.get("bot") or not message:
        return jsonify({"status": "ignored"})

    print(f"Message in channel {channel_id} sent by {user_name} : {message}")
    
    # Simple response
    response = f"Received your message: '{message}'"
    
    # Try to log to MongoDB, but don't fail if MongoDB isn't available
    try:
        client = get_mongodb_connection()
        if client:
            db = client.get_database("freq_questions")
            queries_collection = db.get_collection("queries")
            
            query_record = {
                "channel_id": channel_id,
                "user_name": user_name,
                "message": message,
                "timestamp": datetime.now()
            }
            queries_collection.insert_one(query_record)
            client.close()
            response += " (logged to database)"
    except Exception as e:
        print(f"MongoDB error: {str(e)}")
        response += " (not logged to database due to error)"
        
    return jsonify({"text": response})
    
@app.errorhandler(404)
def page_not_found(e):
    return "Not Found", 404

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))