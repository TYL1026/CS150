from flask import Flask, request, jsonify
from llmproxy import generate, pdf_upload

app = Flask(__name__)

# First upload the handbook and get the session
result = pdf_upload(
    path="1.pdf",
    strategy="smart",
    description="Tufts CS Handbook",
    session_id="tufts-cs-handbook"
)
print("PDF Upload Result:", result)

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

    # Generate a response using LLMProxy with RAG enabled
    response = generate(
        model='4o-mini',
        system='You are a knowledgeable Tufts CS advisor. Use the provided handbook to answer questions about courses, requirements, and policies accurately.',
        query=message,
        temperature=0.0,
        lastk=0,
        session_id='tufts-cs-handbook',
        rag_usage=True,
        rag_threshold=0.6,
        rag_k=3
    )

    response_text = response['response']
    
    # Send response back
    print(response_text)

    return jsonify({"text": response_text})
    
@app.errorhandler(404)
def page_not_found(e):
    return "Not Found", 404

if __name__ == "__main__":
    app.run()