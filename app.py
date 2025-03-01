import requests
from flask import Flask, request, jsonify
from llmproxy import generate, TuftsCSAdvisor
import uuid
from datetime import datetime

app = Flask(__name__)
# Use a dictionary to store user-specific advisor instances and their state
user_advisors = {}

@app.route('/')
def hello_world():
   return jsonify({"text":'Hello from Koyeb - you reached the main page!'})

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
        
        return jsonify({"text": response})

    except Exception as e:
        print(f"Error processing request: {str(e)}")
        return jsonify({"text": f"Error: {str(e)}"}), 500
    
@app.errorhandler(404)
def page_not_found(e):
    return "Not Found", 404

if __name__ == "__main__":
    # app.run(threaded=True)  # Enable threading for concurrent requests
    app.run(debug=True, port=5000)
