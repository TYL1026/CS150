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

# Known courses cache
known_courses = set()
has_extracted_courses = False

# Initialize by uploading the handbook
handbook_result = pdf_upload(
    path="1.pdf",
    strategy="smart",
    session_id="tufts-handbook"
)
print("Handbook upload result:", handbook_result)

def extract_known_courses():
    """Extract course numbers mentioned in the document"""
    global known_courses, has_extracted_courses
    
    if has_extracted_courses:
        return known_courses
    
    try:
        # Query to extract course numbers from the document
        response = generate(
            model='4o-mini',
            system='You are a tool that extracts CS course numbers mentioned in documents. List ONLY course numbers explicitly mentioned.',
            query='Please list ALL course numbers (e.g., CS111, CS112, etc.) that are explicitly mentioned in the document. Format your response as a simple comma-separated list of course numbers only. Do not include any other text or explanations.',
            temperature=0.0,
            session_id='tufts-handbook-extraction',
            rag_usage=True
        )
        
        # Parse the response to extract course numbers
        if isinstance(response, dict):
            course_list = response.get('response', '')
        else:
            course_list = response
            
        # Extract course numbers using regex
        course_numbers = re.findall(r'CS\s*\d+', course_list, re.IGNORECASE)
        
        # Add to known courses set
        for course in course_numbers:
            # Normalize formatting (remove spaces)
            normalized = re.sub(r'\s+', '', course).upper()
            known_courses.add(normalized)
            
        print(f"Extracted {len(known_courses)} known courses: {', '.join(known_courses)}")
        has_extracted_courses = True
        
    except Exception as e:
        print(f"Error extracting courses: {e}")
        
    return known_courses

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
        advisor_msg = f"Question from @{user}:\n\n{message}\n\nPlease respond directly to the student."
        
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
    
    # Extract known courses if we haven't already
    known_courses = extract_known_courses()
    
    # Check if the message is asking about a specific course
    course_match = re.search(r'CS\s*\d+', message, re.IGNORECASE)
    if course_match:
        # Extract the course number
        course_number = course_match.group(0)
        normalized_course = re.sub(r'\s+', '', course_number).upper()
        
        # Check if this course is in our known courses list
        # If it's not in the list, forward to the advisor
        if normalized_course not in known_courses:
            # Forward the query to the human advisor
            forwarding_success = send_message_to_advisor(user, message, current_advisor)
            
            # Respond to user that their question has been forwarded
            if forwarding_success:
                response_text = f"I don't have specific information about {course_number} in my documentation. I've forwarded your question to our CS advisor (which is you for testing purposes) who will respond to you directly."
            else:
                response_text = f"I don't have specific information about {course_number} in my documentation. I tried to forward your question to our CS advisor but encountered an issue. Please try again later."
            
            print(response_text)
            return jsonify({"text": response_text})
    
    # For courses that are in our known list, or non-course queries, 
    # generate a response using LLMProxy with RAG enabled
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
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))