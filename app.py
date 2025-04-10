import requests
from flask import Flask, request, jsonify, redirect
from advisor import TuftsCSAdvisor
import os
from utils.mongo_config import get_collection, get_mongodb_connection
import json
from utils.log_config import setup_logging
import logging
import traceback
from bson.objectid import ObjectId

app = Flask(__name__)

# log
setup_logging()
logger = logging.getLogger(__name__)


# global variables
RC_BASE_URL = "https://chat.genaiconnect.net/api/v1"

HEADERS = {
    "Content-Type": "application/json",
    "X-Auth-Token": os.environ.get("RC_token"),
    "X-User-Id": os.environ.get("RC_userId")
}

HUMAN_OPERATOR = "@wendan.jiang" 

def send_to_human(user, message, tmid=None):
    """
    Sends a message to a human operator via RocketChat when AI escalation is needed.

    This function handles two scenarios:
    1. Initial escalation: Creates a new message in the human operator channel with alert emoji
    2. Thread continuation: Forwards subsequent user messages to an existing thread
    """
    payload = {}
    if not tmid:
        payload = {
            "channel": HUMAN_OPERATOR,
            "text": f"\U0001F6A8 *Escalation Alert* \U0001F6A8\nUser {user} has requested help. Please respond in the thread. \n\n{message}"
        }
    else:
        payload = {
            "channel": HUMAN_OPERATOR,
            "text": f"🐘 *{user} (student):* {message}",
            "tmid": tmid,
            "tmshow": True
        }
        logger.info("forwarding to thread: " + tmid)

    response = requests.post(f"{RC_BASE_URL}/chat.postMessage", json=payload, headers=HEADERS)

    logger.info("successfully forward message to human")
    logger.info(f"DEBUG: RocketChat API Response: {response.status_code} - {response.text}")
    return response.json()

def send_human_response(user, message, tmid):
    """
    Sends a response from a human operator back to the original user via RocketChat.
    """
    payload = {
        "channel": f"@{user}",  # Send directly to the original user
        "text": f"👤 *{HUMAN_OPERATOR} (Human Advisor):* {message}",
        "tmid": tmid
    }

    response = requests.post(f"{RC_BASE_URL}/chat.postMessage", json=payload, headers=HEADERS)
    logger.info(f"DEBUG: RocketChat API Response: {response.status_code} - {response.text}")
    return response.json()

def send_loading_response(user):
    payload = {
        "channel": f"@{user}",  # Send directly to the original user
        "text": f" :everything_fine_parrot: Processing your inquiry. One moment please..."
    }

    response = requests.post(f"{RC_BASE_URL}/chat.postMessage", json=payload, headers=HEADERS)
    logger.info(f"DEBUG: RocketChat API Response: {response.status_code} - {response.text}")

    if response.status_code == 200:
        json_res = response.json()
        return json_res["message"]["rid"], json_res["message"]["_id"]
    else:
        raise Exception("fail to send loading message")


def format_response_with_buttons(response_text, suggested_questions):
    question_buttons = []
    for i, question in enumerate(suggested_questions, 1):  # Start numbering from 1
        question_buttons.append({
            "type": "button",
            "text": f"{i}",  # Just show the number
            "msg": question,  # Send the full question when clicked
            "msg_in_chat_window": True,
            "msg_processing_type": "sendMessage",
        })

    # Construct response with numbered questions in text and numbered buttons
    numbered_questions = "\n".join([f"{i}. {question}" for i, question in enumerate(suggested_questions, 1)])       
    response = {
        "text": response_text + "\n\n🤔 You might also want to know:\n" + numbered_questions,
        "attachments": [
            {
                "title": "Click a number to ask that question:",
                "actions": question_buttons
            }
        ]
    }
    return response

@app.route('/query', methods=['POST'])
def main():
    """
    Main endpoint for handling user queries to the Tufts CS Advisor.
    
    This endpoint processes incoming messages, manages conversations through RocketChat,
    and provides responses using either cached FAQ answers or live LLM responses.
    It also handles escalation to human operators when necessary.
    """
    data = request.get_json() 

    # Extract relevant information
    user_id = data.get("user_id")
    user_name = data.get("user_name", "Unknown")
    user = user_name
    message = data.get("text", "")
    message_id = data.get("message_id")
    tmid = data.get("tmid", None)

    # Log the incoming request
    logger.info("hit /query endpoint, request data: %s", json.dumps(data, indent=2))
    logger.info(f"{user_name} : {message}")

    # Ignore bot messages
    if data.get("bot") or not message:
        return jsonify({"status": "ignored"})
    
    try:
        # Get MongoDB client from the connection pool
        mongo_client = get_mongodb_connection()
        if not mongo_client:
            return jsonify({"text": "Error connecting to database"}), 500
        
        # ==== THREAD MESSAGE HANDLING ====
        # If message is part of an existing thread, handle direct forwarding without LLM processing
        if tmid:
            logger.info("Processing thread message - direct forwarding without LLM processing")
            thread_collection = get_collection("Users", "threads")
            target_thread = thread_collection.find_one({"thread_id": tmid})

            if not target_thread:
                logger.error("thread with id %s does not exist", tmid)
                return jsonify({"text": f"Error: unable to find a matched thread"}), 500

            print("target_thread")
            print(target_thread)
            
            # Determine message direction (student to human advisor or vice versa)
            forward_human = target_thread.get("forward_human")
            if forward_human == True:
                forward_thread_id = target_thread.get("forward_thread_id")
                logger.info("forwarding a message from student to human advisor (forward_thread_id " + forward_thread_id + ")")
                send_to_human(user, message, forward_thread_id)
            else:
                forward_username = target_thread.get("forward_username")
                forward_thread_id = target_thread.get("forward_thread_id")
                send_human_response(forward_username, message, forward_thread_id)
            
            return jsonify({"success": True}), 200
    
        # ==== USER PROFILE MANAGEMENT ====
        # Get or create user profile for tracking interactions
        user_collection = get_collection("Users", "user")
        user_profile = user_collection.find_one({"user_id": user_id})

        if not user_profile:
            user_profile = {
                "user_id": user_id,
                "username": user_name,
                "last_k": 0,
                "program": "",
                "major": ""
            }
            user_collection.insert_one(user_profile)

        # Update the interaction counter for this user
        lastk = user_profile.get("last_k", 0)
        user_collection.update_one(
                {"user_id": user_id},
                {"$set": {"last_k": lastk + 1}}
            )

        # Initialize the advisor with user profile data
        advisor = TuftsCSAdvisor(user_profile)

        # ==== FAQ MATCHING - EXACT MATCH ====
        # Check if question exactly matches a cached question in the database
        faq_collection = get_collection("freq_questions", "questions")
        faq_doc = faq_collection.find_one({"question": message})
        if faq_doc:
            logger.info("Found exact FAQ match - returning cached response")
            return jsonify(format_response_with_buttons(faq_doc["answer"], faq_doc["suggestedQuestions"]))
        
        # ==== FAQ MATCHING - SEMANTIC MATCH ====
        # If no exact match, try semantic matching with all FAQs
        else:
            # Prompting loading message
            room_id, loading_msg_id = send_loading_response(user_name)

            faq_cursor = faq_collection.find(
                {"question": {"$exists": True}},  
                {"_id": 0, "question": 1, "question_id": 1}  # Projection to only return these fields
            )

            faq_list = []
            for doc in faq_cursor:
                faq_list.append(f"{doc['question_id']}: {doc['question']}")
            faq_string = "\n".join(faq_list)
            response_data = json.loads(advisor.get_faq_response(faq_string, message, lastk))

            # Check if LLM found a semantically similar FAQ
            if response_data.get("cached_question_id"):
                faq_answer = faq_collection.find_one({"question_id": int(response_data["cached_question_id"])})
                response_data = {
                    "response": faq_answer["answer"],
                    "suggestedQuestions": faq_answer["suggestedQuestions"]
                }
                logger.info("Found semantic FAQ match - returning cached response")
                return jsonify(format_response_with_buttons(faq_answer["answer"], faq_answer["suggestedQuestions"]))

            # ==== LLM PROCESSING ====
            # No cached or semantic match found, process with LLM
            logger.info("No FAQ match found - processing with LLM")

            response_text = response_data["response"]
            rc_payload = response_data.get("rocketChatPayload") 
            
            # ==== HUMAN ESCALATION ====
            # Check if LLM determined human escalation is needed
            if rc_payload:
                logger.info("rc_payload exists")
                
                # Extract the payload components
                original_question = rc_payload["originalQuestion"]
                llm_answer = rc_payload.get("llmAnswer")
        
                # Format message for human advisor with context
                formatted_string = ""
                if llm_answer:
                    formatted_string = f"\n❓ Student Question: {original_question}\n\n🤖 AI-Generated Answer: {llm_answer}\n\nCan you please review this answer for accuracy and completeness?"
                else:
                    formatted_string = f"\n❓ Student Question: {original_question}"

                # Forward to human advisor and get the response
                forward_res = send_to_human(user, formatted_string)
                # message_id starts a new thread on human advisor side
                advisor_messsage_id = forward_res["message"]["_id"]

                # Create bidirectional thread mapping for ongoing conversation
                thread_item = [{
                    "thread_id": message_id,
                    "forward_thread_id": advisor_messsage_id,
                    "forward_human": True
                }, 
                {
                    "thread_id": advisor_messsage_id,
                    "forward_thread_id": message_id,
                    "forward_human": False,
                    "forward_username": user_name

                }]
                thread_collection = get_collection("Users", "threads")
                thread_collection.insert_many(thread_item)
                
                # delete loading msg
                response = requests.post(f"{RC_BASE_URL}/chat.update", json={
                    "roomId": room_id,
                    "msgId": loading_msg_id,
                    "text": " :coll_doge_gif: Your question has been forwarded to a human academic advisor. To begin your conversation, please click the \"View Thread\" button."
                }, headers=HEADERS)

                print(response.json())

                return jsonify({
                    "text": response_text,
                    "tmid": message_id,
                    "tmshow": True
                })

            # ==== STANDARD LLM RESPONSE ====
            # Return LLM-generated response with suggested follow-up questions
            else:
                logger.info("Returning standard LLM response with suggested questions")

                response = requests.post(f"{RC_BASE_URL}/chat.update", json={
                    "roomId": room_id,
                    "msgId": loading_msg_id,
                    "text": " :kirby_vibing: Ta-da! Your answer is ready!"
                }, headers=HEADERS)

                return format_response_with_buttons(response_data["response"], response_data["suggestedQuestions"])

    except Exception as e:
        traceback.print_exc()
        print(f"Error processing request: {str(e)}")
        return jsonify({"text": f"Error: {str(e)}"}), 500

@app.errorhandler(404)
def page_not_found(e):
    return "Not Found", 404

@app.route('/')
def hello_world():
   return jsonify({"text": 'Hello from Koyeb - you reached the main page!'})


@app.route('/database', methods=['GET', 'POST'])
def view_database():
    """
    Endpoint to display and edit the freq_questions database.
    """
    try:
        # Get MongoDB client from the connection pool
        mongo_client = get_mongodb_connection()
        if not mongo_client:
            return jsonify({"error": "Error connecting to database"}), 500
        
        # Focus specifically on freq_questions database
        db_name = "freq_questions"
        collection_name = "questions"
        
        # Handle form submission for updating documents
        if request.method == 'POST' and request.form.get('action') == 'update':
            doc_id = request.form.get('doc_id')
            question = request.form.get('question')
            answer = request.form.get('answer')
            question_id = request.form.get('question_id')
            
            # Get suggested questions (they come as a list)
            suggested_questions = []
            i = 0
            while True:
                sq = request.form.get(f'suggested_question_{i}')
                if sq is None:
                    break
                suggested_questions.append(sq)
                i += 1
            
            # Convert question_id to integer if it exists
            if question_id:
                try:
                    question_id = int(question_id)
                except ValueError:
                    return "Question ID must be an integer", 400
            
            # Update the document
            collection = mongo_client[db_name][collection_name]
            collection.update_one(
                {"_id": ObjectId(doc_id)},
                {"$set": {
                    "question": question,
                    "answer": answer,
                    "question_id": question_id,
                    "suggestedQuestions": suggested_questions
                }}
            )
            
            # Redirect to avoid form resubmission
            return redirect('/database')
        
        # Handle form submission for adding new documents
        elif request.method == 'POST' and request.form.get('action') == 'add':
            question = request.form.get('question')
            answer = request.form.get('answer')
            
            # Get suggested questions
            suggested_questions = []
            i = 0
            while True:
                sq = request.form.get(f'new_suggested_question_{i}')
                if sq is None or sq == '':
                    break
                suggested_questions.append(sq)
                i += 1
            
            # Get all documents to determine highest question_id
            collection = mongo_client[db_name][collection_name]
            all_docs = list(collection.find({}, {"question_id": 1}))
            
            # Find the highest question_id
            highest_id = 0
            for doc in all_docs:
                if 'question_id' in doc and isinstance(doc['question_id'], int) and doc['question_id'] > highest_id:
                    highest_id = doc['question_id']
            
            # Use the next available ID
            next_id = highest_id + 1
            
            # Insert the new document
            collection.insert_one({
                "question": question,
                "answer": answer,
                "question_id": next_id,
                "suggestedQuestions": suggested_questions
            })
            
            # Redirect to avoid form resubmission
            return redirect('/database')
        
        # Handle document deletion
        elif request.method == 'POST' and request.form.get('action') == 'delete':
            doc_id = request.form.get('doc_id')
            collection = mongo_client[db_name][collection_name]
            collection.delete_one({"_id": ObjectId(doc_id)})
            return redirect('/database')
        
        # Get all documents from freq_questions.questions collection
        collection = mongo_client[db_name][collection_name]
        
        # Sort by question_id for better organization
        documents = list(collection.find({}).sort("question_id", 1))
        
        # Get the highest question_id for new questions
        highest_id = 0
        for doc in documents:
            if 'question_id' in doc and isinstance(doc['question_id'], int) and doc['question_id'] > highest_id:
                highest_id = doc['question_id']
        
        # Convert ObjectId to string for display
        for doc in documents:
            doc['_id'] = str(doc['_id'])
        
        # Generate HTML response
        html_response = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Frequent Questions Database Manager</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 20px; }}
                .container {{ max-width: 1200px; margin: 0 auto; }}
                .card {{ border: 1px solid #ccc; border-radius: 5px; padding: 20px; margin-bottom: 20px; }}
                .question-card {{ background-color: #f9f9f9; margin-bottom: 15px; padding: 15px; border-radius: 5px; }}
                .question-id {{ float: right; background: #e0e0e0; padding: 5px 10px; border-radius: 3px; }}
                .form-group {{ margin-bottom: 10px; }}
                label {{ display: block; margin-bottom: 5px; font-weight: bold; }}
                textarea, input[type="text"], input[type="number"] {{ width: 100%; padding: 8px; margin-bottom: 10px; }}
                textarea {{ height: 100px; }}
                button {{ padding: 8px 15px; background: #4CAF50; color: white; border: none; cursor: pointer; margin-right: 5px; }}
                .delete-btn {{ background: #f44336; }}
                .add-field-btn {{ background: #2196F3; }}
                .suggested-questions {{ margin-top: 10px; }}
                .suggested-question {{ margin-bottom: 5px; }}
                h2 {{ color: #333; }}
                .nav {{ margin-bottom: 20px; }}
                .nav a {{ padding: 8px 15px; background: #607d8b; color: white; text-decoration: none; margin-right: 5px; border-radius: 3px; }}
                .note {{ background-color: #fffacd; padding: 10px; border-radius: 5px; margin-bottom: 15px; }}
            </style>
            <script>
                function addSuggestedQuestion(docId) {{
                    const container = document.getElementById('suggested-questions-' + docId);
                    const count = container.children.length;
                    const newInput = document.createElement('div');
                    newInput.className = 'suggested-question';
                    newInput.innerHTML = `<input type="text" name="suggested_question_${{count}}" placeholder="Suggested Question">`;
                    container.appendChild(newInput);
                }}
                
                function addNewSuggestedQuestion() {{
                    const container = document.getElementById('new-suggested-questions');
                    const count = container.children.length;
                    const newInput = document.createElement('div');
                    newInput.className = 'suggested-question';
                    newInput.innerHTML = `<input type="text" name="new_suggested_question_${{count}}" placeholder="Suggested Question">`;
                    container.appendChild(newInput);
                }}
                
                function confirmDelete(docId) {{
                    if(confirm('Are you sure you want to delete this question?')) {{
                        document.getElementById('delete-form-' + docId).submit();
                    }}
                }}
            </script>
        </head>
        <body>
            <div class="container">
                <h1>Frequent Questions Database Manager</h1>
                
                <div class="nav">
                    <a href="/">Home</a>
                    <a href="/database">Refresh</a>
                </div>
                
                <div class="card">
                    <h2>Add New Question</h2>
                    <div class="note">
                        <strong>Note:</strong> New questions will automatically be assigned the next available ID (currently {highest_id + 1}).
                    </div>
                    <form method="POST">
                        <input type="hidden" name="action" value="add">
                        
                        <div class="form-group">
                            <label for="question">Question:</label>
                            <input type="text" name="question" required>
                        </div>
                        
                        <div class="form-group">
                            <label for="answer">Answer:</label>
                            <textarea name="answer" required></textarea>
                        </div>
                        
                        <div class="form-group">
                            <label>Suggested Questions:</label>
                            <div id="new-suggested-questions" class="suggested-questions">
                                <div class="suggested-question">
                                    <input type="text" name="new_suggested_question_0" placeholder="Suggested Question">
                                </div>
                            </div>
                            <button type="button" class="add-field-btn" onclick="addNewSuggestedQuestion()">Add Another Suggested Question</button>
                        </div>
                        
                        <button type="submit">Add Question</button>
                    </form>
                </div>
                
                <h2>Existing Questions ({len(documents)})</h2>
                
                {
                ''.join([
                    f'''
                    <div class="question-card">
                        <div class="question-id">ID: {doc.get('question_id', 'N/A')}</div>
                        <form method="POST">
                            <input type="hidden" name="action" value="update">
                            <input type="hidden" name="doc_id" value="{doc['_id']}">
                            <input type="hidden" name="question_id" value="{doc.get('question_id', '')}">
                            
                            <div class="form-group">
                                <label for="question">Question:</label>
                                <input type="text" name="question" value="{doc.get('question', '')}" required>
                            </div>
                            
                            <div class="form-group">
                                <label for="answer">Answer:</label>
                                <textarea name="answer" required>{doc.get('answer', '')}</textarea>
                            </div>
                            
                            <div class="form-group">
                                <label>Suggested Questions:</label>
                                <div id="suggested-questions-{doc['_id']}" class="suggested-questions">
                                    {
                                    ''.join([
                                        f'<div class="suggested-question"><input type="text" name="suggested_question_{i}" value="{sq}" placeholder="Suggested Question"></div>'
                                        for i, sq in enumerate(doc.get('suggestedQuestions', []))
                                    ])
                                    }
                                </div>
                                <button type="button" class="add-field-btn" onclick="addSuggestedQuestion('{doc['_id']}')">Add Suggested Question</button>
                            </div>
                            
                            <button type="submit">Update</button>
                            <button type="button" class="delete-btn" onclick="confirmDelete('{doc['_id']}')">Delete</button>
                        </form>
                        
                        <form id="delete-form-{doc['_id']}" method="POST" style="display: none;">
                            <input type="hidden" name="action" value="delete">
                            <input type="hidden" name="doc_id" value="{doc['_id']}">
                        </form>
                    </div>
                    '''
                    for doc in documents
                ])
                }
            </div>
        </body>
        </html>
        """
        
        return html_response
    
    except Exception as e:
        logger.error(f"Error in database view: {str(e)}")
        return f"""
        <!DOCTYPE html>
        <html>
        <head><title>Database Error</title></head>
        <body>
            <h1>Error</h1>
            <p>Error in database view: {str(e)}</p>
            <p><a href="/">Back to Home</a></p>
        </body>
        </html>
        """


if __name__ == "__main__":
    # Register shutdown handler to close MongoDB connection when app stops
    import atexit
    from utils.mongo_config import close_mongodb_connection
    atexit.register(close_mongodb_connection)
    
    app.run(debug=True, host="0.0.0.0", port=5999)