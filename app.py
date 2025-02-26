from flask import Flask, request, jsonify
from llmproxy import generate, pdf_upload
import re
import requests
import os

app = Flask(__name__)

# Rocketchat configuration
ROCKETCHAT_URL = "https://chat.genaiconnect.net/api/v1"
ROCKETCHAT_TOKEN = os.environ.get("RC_token")
ROCKETCHAT_USER_ID = os.environ.get("RC_userId")
CS_ADVISOR = "tony.li672462"

# Initialize by uploading the handbook
handbook_result = pdf_upload(
    path="1.pdf",
    strategy="smart",
    session_id="tufts-handbook"
)
print("Handbook upload result:", handbook_result)

def send_message_to_advisor(user, message):
    """Forward a message to the CS advisor"""
    try:
        url = f"{ROCKETCHAT_URL}/chat.postMessage"
        
        headers = {
            "Content-Type": "application/json",
            "X-Auth-Token": ROCKETCHAT_TOKEN,
            "X-User-Id": ROCKETCHAT_USER_ID
        }
        
        # Format message for advisor
        advisor_msg = f"Question from @{user}:\n\n{message}\n\nPlease respond directly to the student."
        
        payload = {
            "channel": f"@{CS_ADVISOR}",
            "text": advisor_msg
        }
        
        response = requests.post(url, json=payload, headers=headers)
        return response.status_code == 200
    except Exception as e:
        print(f"Error forwarding to advisor: {e}")
        return False

@app.route('/')
def hello_world():
   return jsonify({"text":'Hello from Koyeb - you reached the main page!'})

@app.route('/query', methods=['POST'])
def main():
    data = request.get_json() 

    # Extract relevant information
    user = data.get("user_name", "Unknown")
    message = data.get("text", "")

    print(data)

    # Ignore bot messages
    if data.get("bot") or not message:
        return jsonify({"status": "ignored"})

    print(f"Message from {user} : {message}")
    
    # Check if the message is asking about a specific course
    course_match = re.search(r'CS\s*\d+', message, re.IGNORECASE)
    if course_match:
        # Extract the course number
        course_number = course_match.group(0)
        
        # Forward the query to the human advisor
        send_message_to_advisor(user, message)
        
        # Respond to user that their question has been forwarded
        response_text = f"I don't have specific information about {course_number} in my documentation. I've forwarded your question to our CS advisor who will respond to you directly."
        
        print(response_text)
        return jsonify({"text": response_text})

    # For non-course queries, generate a response using LLMProxy with RAG enabled
    response = generate(
        model='4o-mini',
        system='You are a Tufts CS advisor. Use the handbook to answer questions accurately. Never make up information that is not in the handbook.',
        query=message,
        temperature=0.0,
        lastk=0,
        session_id='tufts-handbook',
        rag_usage=True,    # Enable RAG
        rag_threshold=0.5,
        rag_k=3
    )

    if isinstance(response, dict):
        response_text = response.get('response', '')
    else:
        response_text = response
    
    # Send response back
    print(response_text)

    return jsonify({"text": response_text})
    
@app.errorhandler(404)
def page_not_found(e):
    return "Not Found", 404

if __name__ == "__main__":
    app.run()