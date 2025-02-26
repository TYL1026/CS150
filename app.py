from flask import Flask, request, jsonify
from llmproxy import generate, pdf_upload
import re
import requests
import os

app = Flask(__name__)

# Rocketchat configuration
ROCKETCHAT_URL = "https://chat.genaiconnect.net/api/v1"
ROCKETCHAT_TOKEN = os.environ.get("RC_token", "346LviduHcAOp0cjBmsvayH7_q48b4TFbsJHekuJ08U")
ROCKETCHAT_USER_ID = os.environ.get("RC_userId", "QzJoYYTGgNNbZEnty")
CONFIDENCE_THRESHOLD = 0.6  # Threshold for confidence in answers

# Initialize by uploading the handbook
handbook_result = pdf_upload(
    path="1.pdf",
    strategy="smart",
    session_id="tufts-handbook"
)
print("Handbook upload result:", handbook_result)

def send_message_to_advisor(user, message, advisor):
    """Forward a message to the specified CS advisor"""
    try:
        url = f"{ROCKETCHAT_URL}/chat.postMessage"
        
        headers = {
            "Content-Type": "application/json",
            "X-Auth-Token": ROCKETCHAT_TOKEN,
            "X-User-Id": ROCKETCHAT_USER_ID
        }
        
        # Format message for advisor
        advisor_msg = f"Question from @{user}:\n\nwhat is cs112?\n\nPlease respond directly to the student."
        
        payload = {
            "channel": f"@{advisor}",
            "text": advisor_msg
        }
        
        print(f"Attempting to send message to @{advisor} with payload: {payload}")
        response = requests.post(url, json=payload, headers=headers)
        
        if response.status_code == 200:
            print(f"Successfully forwarded message to advisor. Response: {response.json()}")
            return True
        else:
            print(f"Error forwarding to advisor. Status code: {response.status_code}, Response: {response.text}")
            return False
            
    except Exception as e:
        print(f"Exception when forwarding to advisor: {e}")
        return False

def check_document_confidence(query):
    """Check if we have relevant information about this query in our document"""
    try:
        # Use a test query to check if we have information
        test_response = generate(
            model='4o-mini',
            system="""You are a document relevance checker. Your job is ONLY to determine if the 
                   provided document contains specific information about the query. 
                   Respond with EXACTLY "YES" if the document contains relevant information
                   about the query, and "NO" if it does not. DO NOT include any other text.""",
            query=f"Does the document contain specific information about {query}?",
            temperature=0.0,
            session_id='tufts-handbook-check',
            rag_usage=True,
            rag_threshold=0.4,
            rag_k=3
        )
        
        if isinstance(test_response, dict):
            result = test_response.get('response', '')
            rag_context = test_response.get('rag_context', [])
            
            # Get confidence score if available
            confidence = 0
            if rag_context and isinstance(rag_context, list) and len(rag_context) > 0:
                confidence = float(rag_context[0].get('score', 0))
                
            print(f"Document check result: {result}, confidence: {confidence}")
            
            # Check the result
            has_info = "YES" in result.upper() and confidence >= CONFIDENCE_THRESHOLD
            return has_info, confidence
            
        return False, 0
        
    except Exception as e:
        print(f"Error checking document confidence: {e}")
        return False, 0

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
    
    # For testing purposes, make the current user the advisor
    current_advisor = user
    
    # Check if this is a course-related question
    course_match = re.search(r'CS\s*\d+', message, re.IGNORECASE)
    if course_match:
        course_number = course_match.group(0)
        
        # Check if we have information about this course in our document
        has_info, confidence = check_document_confidence(course_number)
        
        if not has_info:
            # We don't have good information about this course, forward to advisor
            forwarding_success = send_message_to_advisor(user, message, current_advisor)
            
            if forwarding_success:
                response_text = f"I don't have specific information about {course_number} in my documentation (confidence: {confidence:.2f}). I've forwarded your question to our CS advisor (which is you for testing purposes) who will respond to you directly."
            else:
                response_text = f"I don't have specific information about {course_number} in my documentation. I tried to forward your question to our CS advisor but encountered an issue."
            
            print(response_text)
            return jsonify({"text": response_text})
    
    # We either have information about the course or this is a non-course query
    # Generate a response using LLMProxy with RAG
    response = generate(
        model='4o-mini',
        system='You are a Tufts CS advisor. Use the handbook to answer questions accurately. Never make up information that is not in the handbook. If you are unsure, say so explicitly.',
        query=message,
        temperature=0.2,
        lastk=0,
        session_id='tufts-handbook',
        rag_usage=True,
        rag_threshold=CONFIDENCE_THRESHOLD,
        rag_k=3
    )
    
    # Get the response and check for uncertainty indicators
    if isinstance(response, dict):
        response_text = response.get('response', '')
        rag_context = response.get('rag_context', [])
        
        # Check confidence
        if rag_context and isinstance(rag_context, list) and len(rag_context) > 0:
            confidence = float(rag_context[0].get('score', 0))
            print(f"Response confidence: {confidence}")
            
            # Check if the confidence is too low or if the response indicates uncertainty
            uncertainty_phrases = ["i'm not sure", "i don't know", "not in the document", "not enough information"]
            if confidence < CONFIDENCE_THRESHOLD or any(phrase in response_text.lower() for phrase in uncertainty_phrases):
                # Forward to advisor as a fallback
                forwarding_success = send_message_to_advisor(user, message, current_advisor)
                
                if forwarding_success:
                    response_text += f"\n\nI'm not fully confident in my answer (confidence: {confidence:.2f}), so I've also forwarded your question to our CS advisor who will respond directly."
    else:
        response_text = response
    
    # Send response back
    print(response_text)
    return jsonify({"text": response_text})
    
@app.errorhandler(404)
def page_not_found(e):
    return "Not Found", 404

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))