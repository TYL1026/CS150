import requests
from flask import Flask, request, jsonify
from llmproxy import generate, TuftsCSAdvisor
import uuid
from datetime import datetime
from pymongo import MongoClient
import os
import re

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
   return jsonify({"text": 'Hello from Koyeb - you reached the main page!'})

@app.route('/query', methods=['POST'])
def main():
    data = request.get_json() 

    # Extract relevant information
    channel_id = data.get("channel_id")
    if not channel_id:
        channel_id = data.get("dC9Suu7AujjGywutjiQPJmyQ7xNwGxWFT3")
    if not channel_id:
        channel_id = str(uuid.uuid4())
        
    user_name = data.get("user_name", "Unknown")
    message = data.get("text", "")

    print(f"Received request: {data}")

    # Ignore bot messages
    if data.get("bot") or not message:
        return jsonify({"status": "ignored"})

    print(f"Message in channel {channel_id} sent by {user_name} : {message}")

    # First, try to find a matching question in the database
    try:
        client = get_mongodb_connection()
        if client:
            db = client.get_database("freq_questions")
            questions_collection = db.get_collection("questions")
            
            # Search for matching questions - first try exact match
            db_result = questions_collection.find_one({
                "question": {"...."}
            })
            
            # If no exact match, try partial match
            if not db_result:
                db_result = questions_collection.find_one({
                    "question": {"$regex": re.escape(message), "$options": "i"}
                })
            
            # If still no match, try keyword search
            if not db_result:
                keywords = [word for word in message.lower().split() if len(word) > 3]
                if keywords:
                    keyword_query = {"$or": [
                        {"question": {"$regex": keyword, "$options": "i"}} for keyword in keywords
                    ]}
                    db_result = questions_collection.find_one(keyword_query)
            
            # If we found a match in the database, return it
            if db_result and "answer" in db_result:
                print("Found answer in database")
                client.close()
                return jsonify({"text": db_result["answer"]})
                
            # Get a few suggested questions from the database to offer as buttons
            # This could be based on popularity, relevance to the query, or just general FAQs
            suggested_questions = list(questions_collection.find({}, {"question": 1, "_id": 0}).limit(3))
            suggested_questions = [q["question"] for q in suggested_questions if "question" in q]
            
            client.close()
    
    except Exception as e:
        print(f"Error searching database: {str(e)}")
        suggested_questions = []
    
    # If we get here, either the database search failed or no match was found
    # Fall back to the original TuftsCSAdvisor logic
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
        advisor_response = user_advisors[channel_id]["advisor"].get_response(
            query=message, 
            lastk=current_lastk
        )
        
        # If no suggested questions from database, use default ones
        if not suggested_questions:
            suggested_questions = [
                "What are the requirements for the CS graduate program?", 
                "How do I apply for research assistantships?", 
                "What courses should I take in my first semester?"
            ]
        
        # Format the response with suggested question buttons
        response = {
            "text": advisor_response,
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": advisor_response
                    }
                },
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {
                                "type": "plain_text",
                                "text": question[:75] + ("..." if len(question) > 75 else ""),
                                "emoji": True
                            },
                            "value": question
                        } for question in suggested_questions
                    ]
                }
            ]
        }
        
        return jsonify(response)

    except Exception as e:
        print(f"Error processing request: {str(e)}")
        return jsonify({"text": f"Error: {str(e)}"}), 500

@app.errorhandler(404)
def page_not_found(e):
    return "Not Found", 404

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(debug=True, host="0.0.0.0", port=port)
