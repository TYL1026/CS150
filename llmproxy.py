import os
import json
import time
import threading
import queue
import re  # Added for course number pattern matching
from typing import Dict, List, Optional
import requests

# Read proxy config from environment
END_POINT = os.environ.get("endPoint")
API_KEY = os.environ.get("apiKey")

# RocketChat configuration
ROCKETCHAT_URL = "https://chat.genaiconnect.net/api/v1"
ROCKETCHAT_TOKEN = os.environ.get("RC_token", "346LviduHcAOp0cjBmsvayH7_q48b4TFbsJHekuJ08U")
ROCKETCHAT_USER_ID = os.environ.get("RC_userId", "QzJoYYTGgNNbZEnty")

# CS Advisor username (the human expert who will receive questions)
CS_ADVISOR_USERNAME = os.environ.get("CS_ADVISOR", "tony.li672462")

# LLM Configuration
DEFAULT_MODEL = "4o-mini"
DEFAULT_SESSION_ID = "CS_ADVISING_BOT"
CONFIDENCE_THRESHOLD = 0.85  # Even higher threshold to be extremely conservative

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
        
        # Create a system prompt that leverages the uploaded PDF content
        self.system_prompt = """
        You are a CS department advising chatbot for Tufts University. Your job is to answer questions about CS courses, 
        degree requirements, prerequisites, and other department-related information.
        
        Base your answers ONLY on the CS department PDF document that has been uploaded to your context.
        
        IMPORTANT: If you cannot find SPECIFIC information about a course, requirement or topic in the PDF:
        1. DO NOT make up or hallucinate any information
        2. Clearly state: "I don't have specific information about [topic] in my current documentation"
        3. Say: "I'll ask our CS advisor for help with this question"
        4. Include the tag $EXPERT_NEEDED$ at the end of your response
        
        For questions about specific courses (like CS101, CS160, etc.), ONLY provide information if the exact course 
        number is mentioned in the PDF. DO NOT guess or infer course content if you can't find it.
        
        When you're uncertain about any information, even if you think you might know, err on the side of caution and 
        consult the human expert instead of providing potentially incorrect information.
        
        Use a conversational, helpful tone and be concise.
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
    
    def message_listener(self):
        """Thread that listens for and processes new messages"""
        CHANNEL = "GENERAL"  # Monitor this channel - add more as needed
        
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
        
        # Process the message with LLM
        response, need_expert = self.process_with_llm(content, session)
        
        # Add bot's response to history
        session.add_message("bot", response)
        
        # Send response to user
        self.send_message(channel_or_room_id, response)
        
        # If expert help is needed, forward the question
        if need_expert:
            question_id = f"q_{int(time.time())}_{user_id[-5:]}"
            session.add_pending_question(question_id, content)
            
            # Format a nice message for the expert
            expert_msg = (
                f"Question from user @{username} (ID: {question_id}):\n\n"
                f"{content}\n\n"
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
                temperature=0.3,  # Lower temperature to reduce creativity/hallucination
                lastk=10,
                session_id=f"{DEFAULT_SESSION_ID}_{session.user_id}",
                rag_threshold=CONFIDENCE_THRESHOLD,
                rag_usage=True,  # Enable RAG to use uploaded PDF
                rag_k=3
            )
            
            if isinstance(response_data, dict) and 'response' in response_data:
                response = response_data['response']
                
                # Check if expert is needed based on tag or RAG confidence
                need_expert = False
                
                # Check for explicit expert request tag
                if "$EXPERT_NEEDED$" in response:
                    need_expert = True
                    # Remove the tag from the response
                    response = response.replace("$EXPERT_NEEDED$", "")
                
                # Check for any course number mentions that might need verification
                if re.search(r'CS\s?\d{3}', query, re.IGNORECASE) and "I don't have specific information" not in response:
                    # Courses were mentioned in the query but we didn't explicitly say we lack info
                    # This indicates we might be hallucinating, so let's double-check
                    
                    # Check RAG context confidence if available
                    rag_context = response_data.get('rag_context', [])
                    
                    # If no RAG context or low confidence, force expert consult
                    if not rag_context or (isinstance(rag_context, list) and (not rag_context or float(rag_context[0].get('score', 0)) < 0.8)):
                        need_expert = True
                        response = "I don't have specific information about this course in my current documentation. I'll ask our CS advisor for help with this question."
                
                # Always check RAG context confidence
                rag_context = response_data.get('rag_context', [])
                if isinstance(rag_context, list) and (not rag_context or float(rag_context[0].get('score', 0)) < CONFIDENCE_THRESHOLD):
                    need_expert = True
                    
                    # If not already indicating an expert referral, add it
                    if "ask a human CS advisor" not in response.lower() and "ask our CS advisor" not in response.lower():
                        response = "I don't have enough specific information to answer this question accurately. I'll ask our CS advisor at Tufts to help with this. I'll get back to you with their response soon."
                
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

def text_upload(
    text: str,    
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
        'text': (None, text, "application/text")
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