import os
import json
import time
import threading
import queue
import re
from typing import Dict, List, Optional
import requests

# Read proxy config from environment
END_POINT = os.environ.get("endPoint")
API_KEY = os.environ.get("apiKey")

# RocketChat configuration
ROCKETCHAT_URL = "https://chat.genaiconnect.net/api/v1"
ROCKETCHAT_TOKEN = os.environ.get("RC_token", "346LviduHcAOp0cjBmsvayH7_q48b4TFbsJHekuJ08U")
ROCKETCHAT_USER_ID = os.environ.get("RC_userId", "QzJoYYTGgNNbZEnty")

# CS Advisor username 
CS_ADVISOR_USERNAME = "tony.li672462"  # Hardcoded to the specific advisor

# LLM Configuration
DEFAULT_MODEL = "4o-mini"
DEFAULT_SESSION_ID = "CS_ADVISING_BOT"

# Track user conversations
class UserSession:
    def __init__(self, user_id, username):
        self.user_id = user_id
        self.username = username
        self.conversation_history = []
        self.pending_expert_questions = {}  # question_id -> question_text
        self.last_interaction = time.time()
    
    def add_message(self, sender, message):
        self.conversation_history.append({
            "sender": sender,
            "message": message,
            "timestamp": time.time()
        })
        self.last_interaction = time.time()
    
    def add_pending_question(self, question_id, question_text):
        self.pending_expert_questions[question_id] = question_text
    
    def resolve_pending_question(self, question_id):
        if question_id in self.pending_expert_questions:
            del self.pending_expert_questions[question_id]
    
    def get_recent_context(self, max_messages=5):
        recent = self.conversation_history[-max_messages:] if len(self.conversation_history) > max_messages else self.conversation_history
        return "\n".join([f"{msg['sender']}: {msg['message']}" for msg in recent])

class CSAdvisingChatbot:
    def __init__(self):
        # RocketChat API headers
        self.auth_headers = {
            "Content-Type": "application/json",
            "X-Auth-Token": ROCKETCHAT_TOKEN,
            "X-User-Id": ROCKETCHAT_USER_ID
        }
        
        # User sessions and expert response tracking
        self.sessions = {}  # user_id -> UserSession
        self.expert_responses_queue = queue.Queue()
        
        # A list of known CS courses from the document
        # This will be populated after document analysis
        self.known_courses = set()
        
        # Create a system prompt with a strong emphasis on avoiding hallucination
        self.system_prompt = """
        You are a CS department advising chatbot for Tufts University. Your job is to answer questions 
        about CS courses, degree requirements, prerequisites, and other department-related information.
        
        Base your answers ONLY on the CS department PDF document that has been uploaded to your context.
        
        NEVER make up or hallucinate information that is not explicitly stated in the document.
        """
        
        # Start threads for handling message processing
        self.running = True
        self.last_checked_time = {}  # channel -> timestamp
        self.message_thread = threading.Thread(target=self.message_listener)
        self.expert_response_thread = threading.Thread(target=self.expert_response_handler)
        self.message_thread.daemon = True
        self.expert_response_thread.daemon = True
    
    def start(self):
        """Start the chatbot"""
        print("Starting CS Advising Chatbot...")
        
        # Start the monitoring threads
        self.message_thread.start()
        self.expert_response_thread.start()
    
    def stop(self):
        """Stop the chatbot gracefully"""
        self.running = False
        self.message_thread.join(timeout=1.0)
        self.expert_response_thread.join(timeout=1.0)
    
    def analyze_document_for_courses(self):
        """Analyze the RAG document to extract mentioned course numbers"""
        try:
            # Use a query specifically designed to extract course numbers
            extraction_prompt = """
            Please list ALL course numbers (e.g., CS101, CS160, etc.) that are explicitly mentioned 
            in the document. Format your response as a simple comma-separated list of course numbers 
            only (e.g., CS101, CS105, CS160). Do not include any other text, explanations, or courses 
            that aren't explicitly mentioned.
            """
            
            response_data = generate(
                model=DEFAULT_MODEL,
                system="You are a tool that extracts CS course numbers mentioned in documents. List ONLY course numbers explicitly mentioned.",
                query=extraction_prompt,
                temperature=0.0,  # Zero temperature for deterministic output
                session_id=f"{DEFAULT_SESSION_ID}_EXTRACTION",
                rag_usage=True  # Enable RAG to use uploaded PDF
            )
            
            if isinstance(response_data, dict) and 'response' in response_data:
                course_list = response_data['response']
                
                # Extract course numbers using regex
                course_numbers = re.findall(r'CS\s*\d+', course_list, re.IGNORECASE)
                
                # Add to known courses set
                for course in course_numbers:
                    # Normalize formatting (remove spaces)
                    normalized = re.sub(r'\s+', '', course).upper()
                    self.known_courses.add(normalized)
                
                print(f"Extracted {len(self.known_courses)} known courses from document: {', '.join(self.known_courses)}")
            
        except Exception as e:
            print(f"Error extracting course numbers from document: {e}")
    
    def message_listener(self):
        """Thread that listens for and processes new messages"""
        CHANNEL = "GENERAL"  # Monitor this channel - add more as needed
        
        # First, analyze the document to extract course numbers
        self.analyze_document_for_courses()
        
        while self.running:
            try:
                # Check for new messages in GENERAL channel
                self.check_channel_messages(CHANNEL)
                
                # Check for direct messages to the bot
                self.check_direct_messages()
                
                # Don't hammer the API
                time.sleep(2)
                
            except Exception as e:
                print(f"Error in message listener: {e}")
                time.sleep(5)  # Back off on error
    
    def check_channel_messages(self, channel):
        """Check for new messages in a channel"""
        try:
            # Get channel history
            url = f"{ROCKETCHAT_URL}/channels.history"
            payload = {
                "roomName": channel,
                "count": 10
            }
            
            response = requests.get(url, params=payload, headers=self.auth_headers)
            
            if response.status_code != 200:
                print(f"Error getting messages from {channel}: {response.status_code}")
                return
                
            data = response.json()
            
            if 'messages' in data:
                last_timestamp = self.last_checked_time.get(channel, 0)
                
                for message in data['messages']:
                    # Skip messages we've seen or that are from the bot
                    msg_timestamp = message.get('ts', 0)
                    if msg_timestamp <= last_timestamp or message['u']['_id'] == ROCKETCHAT_USER_ID:
                        continue
                    
                    # Process this message
                    self.handle_message(message, channel)
                    
                    # Update timestamp
                    if msg_timestamp > last_timestamp:
                        last_timestamp = msg_timestamp
                
                # Store the latest timestamp
                self.last_checked_time[channel] = last_timestamp
                
        except Exception as e:
            print(f"Error checking messages for {channel}: {e}")
    
    def check_direct_messages(self):
        """Check for direct messages to the bot"""
        try:
            # Get direct messages
            url = f"{ROCKETCHAT_URL}/im.list"
            response = requests.get(url, headers=self.auth_headers)
            
            if response.status_code != 200:
                print(f"Error getting DM list: {response.status_code}")
                return
                
            data = response.json()
            
            # Process each DM room
            if 'ims' in data:
                for dm in data['ims']:
                    room_id = dm.get('_id')
                    if not room_id:
                        continue
                        
                    # Check if there are new messages
                    self.check_dm_messages(room_id)
                    
        except Exception as e:
            print(f"Error checking direct messages: {e}")
    
    def check_dm_messages(self, room_id):
        """Check for new messages in a DM room"""
        try:
            # Get DM history
            url = f"{ROCKETCHAT_URL}/im.history"
            payload = {
                "roomId": room_id,
                "count": 10
            }
            
            response = requests.get(url, params=payload, headers=self.auth_headers)
            
            if response.status_code != 200:
                print(f"Error getting messages from DM {room_id}: {response.status_code}")
                return
                
            data = response.json()
            
            if 'messages' in data:
                last_timestamp = self.last_checked_time.get(room_id, 0)
                
                for message in data['messages']:
                    # Skip messages we've seen or that are from the bot
                    msg_timestamp = message.get('ts', 0)
                    if msg_timestamp <= last_timestamp or message['u']['_id'] == ROCKETCHAT_USER_ID:
                        continue
                    
                    # Process this message
                    self.handle_message(message, room_id)
                    
                    # Update timestamp
                    if msg_timestamp > last_timestamp:
                        last_timestamp = msg_timestamp
                
                # Store the latest timestamp
                self.last_checked_time[room_id] = last_timestamp
                
        except Exception as e:
            print(f"Error checking DM messages for {room_id}: {e}")
    
    def handle_message(self, message, channel_or_room_id):
        """Process a new message"""
        user_id = message['u']['_id']
        username = message['u']['username']
        content = message['msg']
        
        # Check if this is the CS advisor responding to a question
        if username == CS_ADVISOR_USERNAME and content.startswith("ANSWER:"):
            self.handle_expert_response(message)
            return
        
        # Create or get user session
        if user_id not in self.sessions:
            self.sessions[user_id] = UserSession(user_id, username)
        
        session = self.sessions[user_id]
        session.add_message(username, content)
        
        # Check if this is asking about a specific course
        course_match = re.search(r'CS\s*\d+', content, re.IGNORECASE)
        if course_match:
            course_number = re.sub(r'\s+', '', course_match.group(0)).upper()
            
            # Check if the course is in our known list
            if course_number not in self.known_courses:
                # Course not in our documentation, forward to expert directly
                return self.forward_to_expert(session, content, channel_or_room_id, course_number)
        
        # Process normal questions with LLM
        response, need_expert = self.process_with_llm(content, session)
        
        # Add bot's response to history
        session.add_message("bot", response)
        
        # Send response to user
        self.send_message(channel_or_room_id, response)
        
        # If expert help is needed, forward the question
        if need_expert:
            self.forward_to_expert(session, content, channel_or_room_id)
    
    def forward_to_expert(self, session, question, channel_or_room_id, course_number=None):
        """Forward a question to the human expert"""
        question_id = f"q_{int(time.time())}_{session.user_id[-5:]}"
        session.add_pending_question(question_id, question)
        
        # User notification
        if course_number:
            response = f"I don't have information about {course_number} in my documentation. I'll ask our CS advisor for help with this question."
        else:
            response = "I don't have enough information to answer this question accurately. I'll ask our CS advisor for help with this."
        
        # Add bot's response to history
        session.add_message("bot", response)
        
        # Send response to user
        self.send_message(channel_or_room_id, response)
        
        # Format a nice message for the expert
        expert_msg = (
            f"Question from user @{session.username} (ID: {question_id}):\n\n"
            f"{question}\n\n"
            f"Please reply with:\n"
            f"ANSWER: {question_id}\n"
            f"Your response here..."
        )
        
        # Send to CS advisor
        self.send_message(f"@{CS_ADVISOR_USERNAME}", expert_msg)
    
    def handle_expert_response(self, message):
        """Process a response from the CS advisor"""
        content = message['msg']
        
        try:
            # Extract question ID - format is "ANSWER: q_timestamp_userid"
            first_line = content.split('\n')[0]
            question_id = first_line[len("ANSWER:"):].strip()
            
            # Extract the actual answer (everything after the first line)
            answer = '\n'.join(content.split('\n')[1:]).strip()
            
            # Add to expert responses queue for processing
            response_data = {
                "question_id": question_id,
                "answer": answer
            }
            self.expert_responses_queue.put(response_data)
            
        except Exception as e:
            print(f"Error parsing expert response: {e}")
    
    def expert_response_handler(self):
        """Thread that processes expert responses and forwards them to users"""
        while self.running:
            try:
                # Check if there are any expert responses
                if self.expert_responses_queue.empty():
                    time.sleep(1)
                    continue
                
                # Get the next response
                response_data = self.expert_responses_queue.get(block=False)
                question_id = response_data.get("question_id")
                answer = response_data.get("answer")
                
                # Find which user was waiting for this answer
                user_found = False
                for user_id, session in self.sessions.items():
                    if question_id in session.pending_expert_questions:
                        # Found the user waiting for this answer
                        user_found = True
                        
                        # Format response for the user
                        user_msg = (
                            f"I have an answer from our CS advisor:\n\n"
                            f"{answer}"
                        )
                        
                        # Send to user
                        self.send_message(f"@{session.username}", user_msg)
                        
                        # Add to conversation history
                        session.add_message("advisor", answer)
                        
                        # Remove from pending questions
                        session.resolve_pending_question(question_id)
                        
                        break
                
                if not user_found:
                    print(f"No user found waiting for answer to question {question_id}")
                
            except queue.Empty:
                # No items in queue
                time.sleep(1)
            except Exception as e:
                print(f"Error in expert response handler: {e}")
                time.sleep(5)
    
    def process_with_llm(self, query, session):
        """Process the query with LLM to generate a response"""
        try:
            # Add recent conversation context
            context = session.get_recent_context()
            full_query = f"{query}\n\nRecent conversation:\n{context}"
            
            # Call LLM with RAG enabled to use the uploaded PDF
            response_data = generate(
                model=DEFAULT_MODEL,
                system=self.system_prompt,
                query=full_query,
                temperature=0.2,  # Low temperature to reduce creativity
                lastk=10,
                session_id=f"{DEFAULT_SESSION_ID}_{session.user_id}",
                rag_usage=True  # Enable RAG to use uploaded PDF
            )
            
            if isinstance(response_data, dict) and 'response' in response_data:
                response = response_data['response']
                
                # Get RAG context confidence
                rag_context = response_data.get('rag_context', [])
                confidence_score = float(rag_context[0].get('score', 0)) if rag_context and isinstance(rag_context, list) and len(rag_context) > 0 else 0
                
                # Check if we need expert help
                # If confidence is low or response contains uncertainty indicators
                need_expert = False
                uncertainty_phrases = [
                    "i'm not sure", 
                    "i don't know", 
                    "i don't have",
                    "i can't find",
                    "not in my documentation",
                    "i'm unable to",
                    "unclear"
                ]
                
                # Look for uncertainty in the response
                if confidence_score < 0.8 or any(phrase in response.lower() for phrase in uncertainty_phrases):
                    need_expert = True
                
                return response.strip(), need_expert
            else:
                # Error handling
                error_msg = "I'm having trouble processing your request. I'll ask a CS advisor to help."
                return error_msg, True
                
        except Exception as e:
            print(f"Error processing with LLM: {e}")
            return "Sorry, I encountered an error. I'll ask a CS advisor to help.", True
    
    def send_message(self, channel, text):
        """Send a message to a Rocket.Chat channel or user"""
        try:
            url = f"{ROCKETCHAT_URL}/chat.postMessage"
            
            payload = {
                "channel": channel,
                "text": text
            }
            
            response = requests.post(url, json=payload, headers=self.auth_headers)
            
            if response.status_code != 200:
                print(f"Error sending message: {response.status_code}")
                
            return response.status_code == 200
            
        except Exception as e:
            print(f"Error sending message: {e}")
            return False

# LLM API Functions
def generate(
    model: str,
    system: str,
    query: str,
    temperature: float | None = None,
    lastk: int | None = None,
    session_id: str | None = None,
    rag_threshold: float | None = 0.5,
    rag_usage: bool | None = False,
    rag_k: int | None = 0
):
    headers = {
        'x-api-key': API_KEY
    }

    request = {
        'model': model,
        'system': system,
        'query': query,
        'temperature': temperature,
        'lastk': lastk,
        'session_id': session_id,
        'rag_threshold': rag_threshold,
        'rag_usage': rag_usage,
        'rag_k': rag_k
    }

    try:
        response = requests.post(END_POINT, headers=headers, json=request)

        if response.status_code == 200:
            res = json.loads(response.text)
            return {'response': res['result'], 'rag_context': res.get('rag_context')}
        else:
            return f"Error: Received response code {response.status_code}"
    except requests.exceptions.RequestException as e:
        return f"An error occurred: {e}"

def pdf_upload(
    path: str,    
    strategy: str | None = None,
    description: str | None = None,
    session_id: str | None = None
):
    params = {
        'description': description,
        'session_id': session_id,
        'strategy': strategy
    }

    multipart_form_data = {
        'params': (None, json.dumps(params), 'application/json'),
        'file': (None, open(path, 'rb'), "application/pdf")
    }

    response = upload(multipart_form_data)
    return response

def upload(multipart_form_data):
    headers = {
        'x-api-key': API_KEY
    }

    try:
        response = requests.post(END_POINT, headers=headers, files=multipart_form_data)
        
        if response.status_code == 200:
            return "Successfully uploaded. It may take a short while for the document to be added to your context"
        else:
            return f"Error: Received response code {response.status_code}"
    except requests.exceptions.RequestException as e:
        return f"An error occurred: {e}"

# Main execution
if __name__ == "__main__":
    # Set up the CS advising chatbot
    chatbot = CSAdvisingChatbot()
    
    # Start the bot
    try:
        # Upload CS department PDF if specified
        pdf_path = os.environ.get("CS_PDF_PATH")
        if pdf_path and os.path.exists(pdf_path):
            print(f"Uploading CS department PDF: {pdf_path}")
            result = pdf_upload(
                path=pdf_path,
                description="CS Department Advising Materials",
                session_id=DEFAULT_SESSION_ID
            )
            print(f"Upload result: {result}")
        
        # Start the chatbot
        chatbot.start()
        print(f"CS Advising Chatbot started. Monitoring for messages...")
        
        # Keep main thread alive
        while True:
            time.sleep(1)
            
    except KeyboardInterrupt:
        print("Shutting down chatbot...")
        chatbot.stop()