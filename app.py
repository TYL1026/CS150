from flask import Flask, request, jsonify
from llmproxy import generate, pdf_upload

app = Flask(__name__)

# Initialize by uploading the handbook
handbook_result = pdf_upload(
    path="1.pdf",
    strategy="smart",
    session_id="tufts-handbook"
)
print("Handbook upload result:", handbook_result)

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
        system='You are a Tufts CS advisor. Use the handbook to answer questions accurately.',
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