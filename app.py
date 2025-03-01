import os
from flask import Flask, request, jsonify
from pymongo import MongoClient
from datetime import datetime

app = Flask(__name__)

# MongoDB connection setup
def get_mongodb_connection():
    try:
        mongodb_uri = "mongodb+srv://li102677:BMILcEhbebhm5s1C@cluster0.aprrt.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"
        client = MongoClient(mongodb_uri)
        # Test the connection
        client.admin.command('ping')
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
            collection_names = db.list_collection_names()
            
            # Record the connection in a collection
            connections = db.get_collection("connections")
            connection_record = {
                "timestamp": datetime.now(),
                "status": "connected"
            }
            connections.insert_one(connection_record)
            
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

@app.route('/questions', methods=['GET'])
def get_all_questions():
    try:
        client = get_mongodb_connection()
        if not client:
            return jsonify({"status": "error", "message": "Failed to connect to MongoDB"}), 500
            
        db = client.get_database("freq_questions")
        questions_collection = db.get_collection("questions")
        
        # Find all documents in the collection
        all_questions = list(questions_collection.find({}, {'_id': 0}))
        
        client.close()
        
        return jsonify({
            "status": "success",
            "count": len(all_questions),
            "questions": all_questions
        })
    except Exception as e:
        return jsonify({
            "status": "error", 
            "message": str(e)
        }), 500

@app.route('/questions/search', methods=['GET'])
def search_questions():
    try:
        # Get search parameters
        keyword = request.args.get('keyword', '')
        
        client = get_mongodb_connection()
        if not client:
            return jsonify({"status": "error", "message": "Failed to connect to MongoDB"}), 500
            
        db = client.get_database("freq_questions")
        questions_collection = db.get_collection("questions")
        
        # Build query
        query = {}
        if keyword:
            query['$or'] = [
                {'question': {'$regex': keyword, '$options': 'i'}},
                {'answer': {'$regex': keyword, '$options': 'i'}}
            ]
        
        # Execute query
        results = list(questions_collection.find(query, {'_id': 0}))
        
        client.close()
        
        return jsonify({
            "status": "success",
            "count": len(results),
            "results": results
        })
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

@app.route('/query', methods=['POST'])
def query():
    try:
        data = request.get_json()
        
        # Extract relevant information
        channel_id = data.get("dC9Suu7AujjGywutjiQPJmyQ7xNwGxWFT3", "unknown_channel")  
        user_name = data.get("user_name", "Unknown")
        message = data.get("text", "")
        
        print(f"Received request: {data}")
        
        # Ignore bot messages
        if data.get("bot") or not message:
            return jsonify({"status": "ignored"})
            
        print(f"Message in channel {channel_id} sent by {user_name} : {message}")
        
        # Log the query to MongoDB
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
                
                # Try to find relevant info in questions collection
                questions_collection = db.get_collection("questions")
                
                # Simple keyword search
                keywords = message.lower().split()
                relevant_docs = []
                
                for keyword in keywords:
                    if len(keyword) > 3:  # Skip short words
                        query = {
                            '$or': [
                                {'question': {'$regex': keyword, '$options': 'i'}},
                                {'answer': {'$regex': keyword, '$options': 'i'}}
                            ]
                        }
                        matches = list(questions_collection.find(query, {'_id': 0}))
                        relevant_docs.extend(matches)
                
                if relevant_docs:
                    # Return the first matching answer
                    response = f"I found this in our database: {relevant_docs[0].get('answer', 'No answer found')}"
                else:
                    response = "I don't have specific information about that in my database."
                
                client.close()
                return jsonify({"text": response})
            else:
                return jsonify({"text": "Could not connect to the database to process your query."})
        except Exception as e:
            print(f"Error processing request: {str(e)}")
            return jsonify({"text": f"Error: {str(e)}"}), 500
    
    except Exception as e:
        print(f"Error processing request: {str(e)}")
        return jsonify({"text": f"Error: {str(e)}"}), 500

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))