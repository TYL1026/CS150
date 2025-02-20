import os
import json
import requests

# Read proxy config from environment
end_point = os.environ.get("endPoint")
api_key = os.environ.get("apiKey")

def generate(
    model: str,
    system: str,
    query: str,
    temperature: float | None = None,
    lastk: int | None = None,
    session_id: str | None = None,
    rag_threshold: float | None = 0.6,
    rag_usage: bool | None = True,
    rag_k: int | None = 3
):
    headers = {
        'x-api-key': api_key
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

    print("Request:", json.dumps(request, indent=2))

    try:
        response = requests.post(end_point, headers=headers, json=request)
        print(f"Response status: {response.status_code}")
        print(f"Response headers: {response.headers}")
        
        if response.status_code == 200:
            res = json.loads(response.text)
            print("RAG Context in response:", res.get('rag_context'))
            return res
        else:
            print(f"Error response: {response.text}")
            return {'result': f"Error: Received response code {response.status_code}"}
    except requests.exceptions.RequestException as e:
        print(f"Request error: {str(e)}")
        return {'result': f"An error occurred: {e}"}

def upload(multipart_form_data):
    headers = {
        'x-api-key': api_key
    }

    # Get upload endpoint
    parts = end_point.split('/')
    upload_endpoint = '/'.join(parts[:-1] + ['upload'])
    print(f"Using upload endpoint: {upload_endpoint}")

    try:
        response = requests.post(upload_endpoint, headers=headers, files=multipart_form_data)
        print(f"Upload response status: {response.status_code}")
        print(f"Upload response: {response.text}")
        
        if response.status_code == 200:
            return "Successfully uploaded. It may take a short while for the document to be added to your context"
        else:
            return f"Error: Upload failed with status {response.status_code}"
    except requests.exceptions.RequestException as e:
        return f"Upload error: {e}"

def pdf_upload(
    path: str,
    strategy: str | None = 'smart',
    description: str | None = None,
    session_id: str | None = None
):
    print(f"Attempting to upload PDF from: {path}")
    if not os.path.exists(path):
        return f"Error: File not found at {path}"

    params = {
        'description': description,
        'session_id': session_id,
        'strategy': strategy
    }

    try:
        with open(path, 'rb') as pdf_file:
            multipart_form_data = {
                'params': (None, json.dumps(params), 'application/json'),
                'file': ('1.pdf', pdf_file, 'application/pdf')
            }

            return upload(multipart_form_data)
    except Exception as e:
        return f"Error reading PDF: {str(e)}"