import requests
from flask import Flask, request, jsonify
from llmproxy import generate, TuftsCSAdvisor
import uuid
from datetime import datetime
from pymongo import MongoClient
from bson.json_util import dumps
import os

app = Flask(__name__)
# Use a dictionary to store user-specific advisor instances and their state
user_advisors = {}

# MongoDB connection setup
def get_mongodb_connection():
    mongodb_uri = "mongodb+srv://li102677:<db_password>@cluster0.aprrt.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"
    # Using the provided password
    # In production, use environment variables instead
    mongodb_password = os.environ.get("MONGODB_PASSWORD", "BMILcEhbebhm5s1C")
    mongodb_uri = mongodb_uri.replace("<db_password>", mongodb_password)
    
    client = MongoClient(mongodb_uri)
    return client

# Function to access the freq_questions database
def get_freq_questions_db():
    client = get_mongodb_connection()
    return client.get_database("freq_questions")

@app.route('/')
def hello_world():
    try:
        # Connect to MongoDB when request comes to "/"
        client = get_mongodb_connection()
        
        # Access a database and collection
        db = client.get_database("tufts_advisor_db")
        collection = db.get_collection("connections")
        
        # Insert a document to verify connection
        connection_record = {
            "timestamp": datetime.now(),
            "status": "connected"
        }
        collection.insert_one(connection_record)
        
        # Get count of all connection records
        connection_count = collection.count_documents({})
        
        # Close the connection
        client.close()
        
        return jsonify({
            "text": "Hello from Koyeb - you reached the main page!",
            "mongodb_status": "connected",
            "connection_count": connection_count
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
    channel_id = data.get("dC9Suu7AujjGywutjiQPJmyQ7xNwGxWFT3")  # Use user_id if provided, or generate one
    user_name = data.get("user_name", "Unknown")
    message = data.get("text", "")

    print(f"Received request: {data}")

    # Ignore bot messages
    if data.get("bot") or not message:
        return jsonify({"status": "ignored"})

    print(f"Message in channel {channel_id} sent by {user_name} : {message}")

    try:
        # Get or create user-specific advisor instance
        if channel_id not in user_advisors:
            print(f"Creating new advisor for user {channel_id}")
            user_advisors[channel_id] = {
                "advisor": TuftsCSAdvisor(session_id=f"Tufts-CS-Advisor-{channel_id}"),
                "lastk": 0,
                "last_active": datetime.now()
            }
            
            # Store new user in MongoDB
            try:
                client = get_mongodb_connection()
                db = client.get_database("tufts_advisor_db")
                users_collection = db.get_collection("users")
                
                user_record = {
                    "channel_id": channel_id,
                    "user_name": user_name,
                    "first_seen": datetime.now(),
                    "last_active": datetime.now()
                }
                users_collection.insert_one(user_record)
                client.close()
            except Exception as e:
                print(f"MongoDB error when storing new user: {str(e)}")
        else:
            # Update lastk and timestamp for existing user
            user_advisors[channel_id]["lastk"] += 1
            user_advisors[channel_id]["last_active"] = datetime.now()
            
            # Update user's last_active in MongoDB
            try:
                client = get_mongodb_connection()
                db = client.get_database("tufts_advisor_db")
                users_collection = db.get_collection("users")
                
                users_collection.update_one(
                    {"channel_id": channel_id},
                    {"$set": {"last_active": datetime.now()}}
                )
                client.close()
            except Exception as e:
                print(f"MongoDB error when updating user: {str(e)}")
        
        # Get current lastk value for this user
        current_lastk = user_advisors[channel_id]["lastk"]
        print(f"User {channel_id} - lastk value: {current_lastk}")
        
        # Generate response using user's dedicated advisor with their specific lastk
        response = user_advisors[channel_id]["advisor"].get_response(
            query=message, 
            lastk=current_lastk
        )
        
        # Log conversation to MongoDB
        try:
            client = get_mongodb_connection()
            db = client.get_database("tufts_advisor_db")
            conversations_collection = db.get_collection("conversations")
            
            conversation_record = {
                "channel_id": channel_id,
                "user_name": user_name,
                "timestamp": datetime.now(),
                "user_message": message,
                "advisor_response": response,
                "lastk": current_lastk
            }
            conversations_collection.insert_one(conversation_record)
            client.close()
        except Exception as e:
            print(f"MongoDB error when logging conversation: {str(e)}")
        
        return jsonify({"text": response})

    except Exception as e:
        print(f"Error processing request: {str(e)}")
        return jsonify({"text": f"Error: {str(e)}"}), 500
    
# Add new routes for querying the freq_questions database
@app.route('/questions', methods=['GET'])
def get_all_questions():
    try:
        # Connect to freq_questions database
        db = get_freq_questions_db()
        
        # Assuming you have a collection called "questions"
        # Change this to match your actual collection name
        questions_collection = db.get_collection("questions")
        
        # Find all documents in the collection
        all_questions = list(questions_collection.find({}, {'_id': 0}))
        
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
        # Get search parameters from the URL query string
        keyword = request.args.get('keyword', '')
        category = request.args.get('category', '')
        
        # Build the query
        query = {}
        if keyword:
            # Search for keyword in question text or answer fields
            # Using case-insensitive search with regex
            query['$or'] = [
                {'question': {'$regex': keyword, '$options': 'i'}},
                {'answer': {'$regex': keyword, '$options': 'i'}}
            ]
        
        if category:
            # Add category filter if provided
            query['category'] = category
        
        # Connect to freq_questions database
        db = get_freq_questions_db()
        questions_collection = db.get_collection("questions")
        
        # Execute the query
        search_results = list(questions_collection.find(query, {'_id': 0}))
        
        return jsonify({
            "status": "success",
            "count": len(search_results),
            "search_parameters": {
                "keyword": keyword,
                "category": category
            },
            "results": search_results
        })
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

@app.route('/questions/<question_id>', methods=['GET'])
def get_question_by_id(question_id):
    try:
        # Connect to freq_questions database
        db = get_freq_questions_db()
        questions_collection = db.get_collection("questions")
        
        # Find the question by its ID
        # Note: If you're using MongoDB's ObjectId, you'll need to convert the string ID
        # from bson.objectid import ObjectId
        # question = questions_collection.find_one({"_id": ObjectId(question_id)})
        
        # If using a string ID field instead of MongoDB's ObjectId
        question = questions_collection.find_one({"id": question_id})
        
        if question:
            # Convert MongoDB _id to string for JSON serialization
            if '_id' in question:
                question['_id'] = str(question['_id'])
                
            return jsonify({
                "status": "success",
                "question": question
            })
        else:
            return jsonify({
                "status": "error",
                "message": f"Question with ID {question_id} not found"
            }), 404
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

@app.errorhandler(404)
def page_not_found(e):
    return "Not Found", 404

if __name__ == "__main__":
    # Ensure the MongoDB password is set
    if os.environ.get("MONGODB_PASSWORD") is None:
        print("WARNING: MONGODB_PASSWORD environment variable not set!")
        print("Set it with: export MONGODB_PASSWORD='your_actual_password'")
    
    # app.run(threaded=True)  # Enable threading for concurrent requests
    app.run(debug=True, port=5000)