import requests
from flask import Flask, request, jsonify
from llmproxy import generate, TuftsCSAdvisor
import uuid
from datetime import datetime
from pymongo import MongoClient
import os

app = Flask(__name__)
# Use a dictionary to store user-specific advisor instances and their state
user_advisors = {}

# Simplified MongoDB connection setup
def get_mongodb_connection():
    try:
        # Basic connection string without complicated options
        mongodb_uri = "mongodb+srv://li102677:BMILcEhbebhm5s1C@cluster0.aprrt.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"
        
        # Create a MongoDB client with minimal settings
        client = MongoClient(mongodb_uri, serverSelectionTimeoutMS=5000)
        
        # Test the connection with a simple command
        client.admin.command('ping')
        print("MongoDB connection successful")
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
            
            # Try to get collection names
            try:
                collection_names = db.list_collection_names()
            except Exception as e:
                collection_names = ["Error listing collections"]
                print(f"Error listing collections: {e}")
            
            # Try to record the connection
            try:
                connections = db.get_collection("connections")
                connection_record = {
                    "timestamp": datetime.now(),
                    "status": "connected"
                }
                connections.insert_one(connection_record)
                client.close()
                print("Inserted connection record")
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
        print(f"Error in root endpoint: {e}")
        return jsonify({
            "text": "Hello from Koyeb - you reached the main page!",
            "mongodb_status": "error",
            "error": str(e)
        })

@app.route('/query', methods=['POST'])
def main():
    data = request.get_json() 

    # Extract relevant information - try different fields
    channel_id = data.get("channel_id")
    if not channel_id:
        channel_id = data.get("dC9Suu7AujjGywutjiQPJmyQ7xNwGxWFT3")
    
    # If still no channel_id, use user_id or generate a random one
    if not channel_id:
        channel_id = data.get("user_id", str(uuid.uuid4()))
        
    user_name = data.get("user_name", "Unknown")
    message = data.get("text", "")

    print(f"Received request: {data}")

    # Ignore bot messages
    if data.get("bot") or not message:
        return jsonify({"status": "ignored"})

    print(f"Message in channel {channel_id} sent by {user_name} : {message}")

    # Try to log conversation to MongoDB
    try:
        client = get_mongodb_connection()
        if client:
            db = client.get_database("freq_questions")
            conversations = db.get_collection("conversations")
            
            conversation_record = {
                "channel_id": channel_id,
                "user_name": user_name,
                "message": message,
                "timestamp": datetime.now()
            }
            conversations.insert_one(conversation_record)
            client.close()
            print("Logged conversation to MongoDB")
    except Exception as e:
        print(f"MongoDB logging error: {str(e)}")

    try:
        # Get or create user-specific advisor instance
        if channel_id not in user_advisors:
            print(f"Creating new advisor for user {channel_id}")
            user_advisors[channel_id] = {
                "advisor": TuftsCSAdvisor(session_id=f"Tufts-CS-Advisor-{channel_id}"),
                "lastk": 0,
                "last_active": datetime.now()
            }
        else:
            # Update lastk and timestamp for existing user
            user_advisors[channel_id]["lastk"] += 1
            user_advisors[channel_id]["last_active"] = datetime.now()
        
        # Get current lastk value for this user
        current_lastk = user_advisors[channel_id]["lastk"]
        print(f"User {channel_id} - lastk value: {current_lastk}")
        
        # Generate response using user's dedicated advisor with their specific lastk
        response = user_advisors[channel_id]["advisor"].get_response(
            query=message, 
            lastk=current_lastk
        )
        
        # Try to log the response to MongoDB
        try:
            client = get_mongodb_connection()
            if client:
                db = client.get_database("freq_questions")
                responses = db.get_collection("responses")
                
                response_record = {
                    "channel_id": channel_id,
                    "user_name": user_name,
                    "user_message": message,
                    "advisor_response": response,
                    "lastk": current_lastk,
                    "timestamp": datetime.now()
                }
                responses.insert_one(response_record)
                client.close()
                print("Logged response to MongoDB")
        except Exception as e:
            print(f"MongoDB response logging error: {str(e)}")
        
        return jsonify({"text": response})

    except Exception as e:
        print(f"Error processing request: {str(e)}")
        return jsonify({"text": f"Error: {str(e)}"}), 500
    
@app.errorhandler(404)
def page_not_found(e):
    return "Not Found", 404

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(debug=True, host="0.0.0.0", port=port)