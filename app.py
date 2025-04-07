import requests
from flask import Flask, request, jsonify
from advisor import TuftsCSAdvisor
import os
from utils.mongo_config import get_collection, get_mongodb_connection
import json
from utils.log_config import setup_logging
import logging
import traceback
from db_manager import init_db_routes

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

    # print(HEADERS)

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
        "text": f" :everything_fine_parrot: Processing your academic inquiry for Tufts MSCS program. One moment please..."
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

                # delete loading msg
                print(f"LINE 302, room_id {room_id}")
                print(f"LINE 302, loading_msg_id {loading_msg_id}")

                requests.post(f"{RC_BASE_URL}/chat.update", json={
                    "roomId": room_id,
                    "msgId": loading_msg_id,
                    "text": " :yay_gif: I've analyzed your inquiry regarding the Tufts MSCS program. Please review the information below."
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

init_db_routes(app)

if __name__ == "__main__":
    # Register shutdown handler to close MongoDB connection when app stops
    import atexit
    from utils.mongo_config import close_mongodb_connection
    atexit.register(close_mongodb_connection)
    
    app.run(debug=True, host="0.0.0.0", port=5999)