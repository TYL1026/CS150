from flask import Flask, request, jsonify
from llmproxy import generate, pdf_upload
import os

app = Flask(__name__)

# Get the handbook path
current_dir = os.path.dirname(os.path.abspath(__file__))
handbook_path = os.path.join(current_dir, "1.pdf")

# Upload handbook and store session ID
upload_result = pdf_upload(
    path=handbook_path,
    strategy="smart",
    description="Tufts CS Handbook",
    session_id="tufts-cs-handbook-2025"
)
print("PDF Upload Result:", upload_result)

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

    # Generate a response using LLMProxy with RAG
    response = generate(
        model='4o-mini',
        system='You are a knowledgeable Tufts CS advisor. Always refer to the provided handbook to answer questions about courses, requirements, and policies. Make sure to quote specific sections when relevant.',
        query=message,
        temperature=0.0,
        lastk=0,
        session_id='tufts-cs-handbook-2025',
        rag_usage=True,
        rag_threshold=0.6,
        rag_k=5
    )

    response_text = response.get('response', '')
    rag_context = response.get('rag_context', '')
    print("RAG Context:", rag_context)
    
    # Send response back
    print("Response:", response_text)

    return jsonify({"text": response_text})
    
@app.errorhandler(404)
def page_not_found(e):
    return "Not Found", 404

if __name__ == "__main__":
    app.run()