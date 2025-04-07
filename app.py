import requests
from flask import Flask, request, jsonify, render_template, Response
from advisor import TuftsCSAdvisor
import os
from utils.mongo_config import get_collection, get_mongodb_connection
import json
from utils.log_config import setup_logging
import logging
import traceback
from bson import ObjectId, json_util

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

class JSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, ObjectId):
            return str(obj)
        return super(JSONEncoder, self).default(obj)
    
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

@app.route('/database', methods=['GET'])
def database_view():
    """
    Displays database contents with CRUD capabilities
    """
    try:
        # Get MongoDB client
        mongo_client = get_mongodb_connection()
        if not mongo_client:
            return jsonify({"error": "Error connecting to database. Please check if MONGO_URI is set properly in your .env file."}), 500
        
        # Build HTML page with database content
        html_content = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>MongoDB Database Manager</title>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <style>
                body {
                    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                    line-height: 1.6;
                    color: #333;
                    max-width: 1200px;
                    margin: 0 auto;
                    padding: 20px;
                }
                h1, h2, h3 {
                    color: #2c3e50;
                }
                .database-section {
                    margin-bottom: 30px;
                    border: 1px solid #ddd;
                    border-radius: 5px;
                    padding: 15px;
                    background-color: #f9f9f9;
                }
                .collection-section {
                    margin: 15px 0;
                    border: 1px solid #e0e0e0;
                    border-radius: 5px;
                    padding: 10px;
                    background-color: white;
                }
                table {
                    width: 100%;
                    border-collapse: collapse;
                    margin-top: 10px;
                    font-size: 14px;
                }
                th, td {
                    padding: 8px 12px;
                    text-align: left;
                    border-bottom: 1px solid #e0e0e0;
                }
                th {
                    background-color: #f2f2f2;
                    font-weight: 600;
                }
                pre {
                    background-color: #f6f8fa;
                    border-radius: 3px;
                    padding: 10px;
                    overflow-x: auto;
                    max-height: 300px;
                    margin: 5px 0;
                }
                button {
                    background-color: #4CAF50;
                    color: white;
                    border: none;
                    padding: 8px 12px;
                    text-align: center;
                    text-decoration: none;
                    display: inline-block;
                    font-size: 14px;
                    margin: 5px 2px;
                    cursor: pointer;
                    border-radius: 4px;
                }
                button.edit {
                    background-color: #2196F3;
                }
                button.delete {
                    background-color: #f44336;
                }
                .hidden {
                    display: none;
                }
                form {
                    margin-top: 15px;
                    padding: 15px;
                    background-color: #f2f2f2;
                    border-radius: 5px;
                }
                textarea, input {
                    width: 100%;
                    padding: 8px;
                    margin: 8px 0;
                    box-sizing: border-box;
                    border: 1px solid #ccc;
                    border-radius: 4px;
                }
                .actions {
                    display: flex;
                    gap: 5px;
                }
                .load-spinner {
                    border: 4px solid #f3f3f3;
                    border-top: 4px solid #3498db;
                    border-radius: 50%;
                    width: 20px;
                    height: 20px;
                    animation: spin 2s linear infinite;
                    display: inline-block;
                    margin-left: 10px;
                }
                @keyframes spin {
                    0% { transform: rotate(0deg); }
                    100% { transform: rotate(360deg); }
                }
            </style>
        </head>
        <body>
            <h1>MongoDB Database Manager</h1>
            <div id="database-container">
        """
        
        # List all databases except admin, local and config
        database_names = [db for db in mongo_client.list_database_names() 
                        if db not in ['admin', 'local', 'config']]
        
        for db_name in database_names:
            html_content += f"""
            <div class="database-section">
                <h2>Database: {db_name}</h2>
            """
            
            collection_names = mongo_client[db_name].list_collection_names()
            
            for coll_name in collection_names:
                html_content += f"""
                <div class="collection-section">
                    <h3>Collection: {coll_name}</h3>
                    <button onclick="loadCollection('{db_name}', '{coll_name}')">View Documents</button>
                    <button onclick="showAddForm('{db_name}', '{coll_name}')">Add New Document</button>
                    
                    <div id="data-{db_name}-{coll_name}" class="data-container"></div>
                    
                    <div id="add-form-{db_name}-{coll_name}" class="form-container hidden">
                        <h4>Add New Document</h4>
                        <form id="add-doc-form-{db_name}-{coll_name}" onsubmit="return addDocument('{db_name}', '{coll_name}')">
                            <textarea id="add-content-{db_name}-{coll_name}" rows="10" placeholder="Enter JSON document">{{
  "field": "value"
}}</textarea>
                            <button type="submit">Add Document</button>
                            <button type="button" onclick="hideAddForm('{db_name}', '{coll_name}')">Cancel</button>
                        </form>
                    </div>
                    
                    <div id="edit-form-{db_name}-{coll_name}" class="form-container hidden">
                        <h4>Edit Document</h4>
                        <form id="edit-doc-form-{db_name}-{coll_name}" onsubmit="return updateDocument('{db_name}', '{coll_name}')">
                            <input type="hidden" id="edit-id-{db_name}-{coll_name}">
                            <textarea id="edit-content-{db_name}-{coll_name}" rows="10"></textarea>
                            <button type="submit">Update Document</button>
                            <button type="button" onclick="hideEditForm('{db_name}', '{coll_name}')">Cancel</button>
                        </form>
                    </div>
                </div>
                """
            
            html_content += "</div>"
            
        html_content += """
            </div>
            
            <script>
                // Function to load collection data
                function loadCollection(dbName, collName) {
                    const container = document.getElementById(`data-${dbName}-${collName}`);
                    container.innerHTML = '<div class="load-spinner"></div> Loading documents...';
                    
                    fetch(`/database/${dbName}/${collName}`)
                        .then(response => response.json())
                        .then(data => {
                            if (data.length === 0) {
                                container.innerHTML = '<p>No documents found in this collection.</p>';
                                return;
                            }
                            
                            let tableHtml = `<table>
                                <tr>
                                    <th>ID</th>
                                    <th>Document</th>
                                    <th>Actions</th>
                                </tr>`;
                                
                            data.forEach(doc => {
                                const id = doc._id;
                                delete doc._id;
                                
                                tableHtml += `<tr>
                                    <td>${id}</td>
                                    <td><pre>${JSON.stringify(doc, null, 2)}</pre></td>
                                    <td class="actions">
                                        <button class="edit" onclick="editDocument('${dbName}', '${collName}', '${id}', ${JSON.stringify(JSON.stringify(doc))})">Edit</button>
                                        <button class="delete" onclick="deleteDocument('${dbName}', '${collName}', '${id}')">Delete</button>
                                    </td>
                                </tr>`;
                            });
                            
                            tableHtml += '</table>';
                            container.innerHTML = tableHtml;
                        })
                        .catch(error => {
                            container.innerHTML = `<p>Error loading documents: ${error.message}</p>`;
                        });
                }
                
                // Show/hide form functions
                function showAddForm(dbName, collName) {
                    document.getElementById(`add-form-${dbName}-${collName}`).classList.remove('hidden');
                }
                
                function hideAddForm(dbName, collName) {
                    document.getElementById(`add-form-${dbName}-${collName}`).classList.add('hidden');
                }
                
                function showEditForm(dbName, collName) {
                    document.getElementById(`edit-form-${dbName}-${collName}`).classList.remove('hidden');
                }
                
                function hideEditForm(dbName, collName) {
                    document.getElementById(`edit-form-${dbName}-${collName}`).classList.add('hidden');
                }
                
                // CRUD operations
                function addDocument(dbName, collName) {
                    const contentField = document.getElementById(`add-content-${dbName}-${collName}`);
                    let content;
                    
                    try {
                        content = JSON.parse(contentField.value);
                    } catch (e) {
                        alert('Invalid JSON. Please check your format.');
                        return false;
                    }
                    
                    fetch(`/database/${dbName}/${collName}`, {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json'
                        },
                        body: JSON.stringify(content)
                    })
                    .then(response => response.json())
                    .then(data => {
                        if (data.error) {
                            alert(`Error: ${data.error}`);
                        } else {
                            alert('Document added successfully');
                            hideAddForm(dbName, collName);
                            contentField.value = '{\n  "field": "value"\n}';
                            loadCollection(dbName, collName);
                        }
                    })
                    .catch(error => {
                        alert(`Error: ${error.message}`);
                    });
                    
                    return false;
                }
                
                function editDocument(dbName, collName, id, contentStr) {
                    const idField = document.getElementById(`edit-id-${dbName}-${collName}`);
                    const contentField = document.getElementById(`edit-content-${dbName}-${collName}`);
                    
                    idField.value = id;
                    contentField.value = JSON.stringify(JSON.parse(contentStr), null, 2);
                    
                    showEditForm(dbName, collName);
                }
                
                function updateDocument(dbName, collName) {
                    const idField = document.getElementById(`edit-id-${dbName}-${collName}`);
                    const contentField = document.getElementById(`edit-content-${dbName}-${collName}`);
                    let content;
                    
                    try {
                        content = JSON.parse(contentField.value);
                    } catch (e) {
                        alert('Invalid JSON. Please check your format.');
                        return false;
                    }
                    
                    fetch(`/database/${dbName}/${collName}/${idField.value}`, {
                        method: 'PUT',
                        headers: {
                            'Content-Type': 'application/json'
                        },
                        body: JSON.stringify(content)
                    })
                    .then(response => response.json())
                    .then(data => {
                        if (data.error) {
                            alert(`Error: ${data.error}`);
                        } else {
                            alert('Document updated successfully');
                            hideEditForm(dbName, collName);
                            loadCollection(dbName, collName);
                        }
                    })
                    .catch(error => {
                        alert(`Error: ${error.message}`);
                    });
                    
                    return false;
                }
                
                function deleteDocument(dbName, collName, id) {
                    if (confirm('Are you sure you want to delete this document?')) {
                        fetch(`/database/${dbName}/${collName}/${id}`, {
                            method: 'DELETE'
                        })
                        .then(response => response.json())
                        .then(data => {
                            if (data.error) {
                                alert(`Error: ${data.error}`);
                            } else {
                                alert('Document deleted successfully');
                                loadCollection(dbName, collName);
                            }
                        })
                        .catch(error => {
                            alert(`Error: ${error.message}`);
                        });
                    }
                }
            </script>
        </body>
        </html>
        """
        
        return Response(html_content, mimetype='text/html')
        
    except Exception as e:
        import traceback
        logger.error(f"Error in database view: {str(e)}\n{traceback.format_exc()}")
        return jsonify({"error": f"Error: {str(e)}"}), 500

@app.route('/database/<db_name>/<collection_name>', methods=['GET', 'POST'])
def collection_management(db_name, collection_name):
    """
    GET: Fetch documents from a collection
    POST: Add a new document to a collection
    """
    try:
        mongo_client = get_mongodb_connection()
        if not mongo_client:
            return jsonify({"error": "Database connection error"}), 500
            
        collection = mongo_client[db_name][collection_name]
        
        if request.method == 'GET':
            # Fetch documents (limit to 100 for performance)
            documents = list(collection.find().limit(100))
            # Convert to JSON
            return Response(
                json.dumps(documents, cls=JSONEncoder),
                mimetype='application/json'
            )
            
        elif request.method == 'POST':
            # Add a new document
            new_doc = request.json
            result = collection.insert_one(new_doc)
            return jsonify({
                "message": "Document added successfully",
                "id": str(result.inserted_id)
            })
            
    except Exception as e:
        logger.error(f"Error in collection management: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/database/<db_name>/<collection_name>/<doc_id>', methods=['PUT', 'DELETE'])
def document_management(db_name, collection_name, doc_id):
    """
    PUT: Update a document
    DELETE: Delete a document
    """
    try:
        mongo_client = get_mongodb_connection()
        if not mongo_client:
            return jsonify({"error": "Database connection error"}), 500
            
        collection = mongo_client[db_name][collection_name]
        
        # Convert string ID to ObjectId if possible
        try:
            object_id = ObjectId(doc_id)
        except:
            # If not a valid ObjectId, use the string directly
            object_id = doc_id
        
        if request.method == 'PUT':
            # Update document
            document = request.json
            
            # Remove _id if present (can't modify _id)
            if '_id' in document:
                del document['_id']
                
            result = collection.update_one({"_id": object_id}, {"$set": document})
            
            if result.matched_count == 0:
                return jsonify({"error": "Document not found"}), 404
                
            return jsonify({
                "message": "Document updated successfully",
                "modified_count": result.modified_count
            })
            
        elif request.method == 'DELETE':
            # Delete document
            result = collection.delete_one({"_id": object_id})
            
            if result.deleted_count == 0:
                return jsonify({"error": "Document not found"}), 404
                
            return jsonify({
                "message": "Document deleted successfully"
            })
            
    except Exception as e:
        logger.error(f"Error in document management: {str(e)}")
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    # Register shutdown handler to close MongoDB connection when app stops
    import atexit
    from utils.mongo_config import close_mongodb_connection
    atexit.register(close_mongodb_connection)
    
    app.run(debug=True, host="0.0.0.0", port=5999)