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

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))