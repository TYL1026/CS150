import os
import json
import requests
import time
from typing import Optional

end_point = os.environ.get("endPoint")
api_key = os.environ.get("apiKey")
current_dir = os.path.dirname(os.path.abspath(__file__))
pdf_path = os.path.join(current_dir, "1.pdf")

def generate(
    model: str,
    system: str,
    query: str,
    temperature: Optional[float] = None,
    lastk: Optional[int] = None,
    session_id: Optional[str] = None,
    rag_threshold: float = 0.5,
    rag_usage: bool = True,
    rag_k: int = 3
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

    try:
        response = requests.post(end_point, headers=headers, json=request)
        if response.status_code == 200:
            res = json.loads(response.text)
            return {'response': res['result'], 'rag_context': res.get('rag_context')}
        else:
            return {'error': f"Error: Received response code {response.status_code}"}
    except requests.exceptions.RequestException as e:
        return {'error': f"An error occurred: {e}"}

def upload(multipart_form_data):
    headers = {
        'x-api-key': api_key
    }

    upload_endpoint = end_point.replace('/generate', '/upload')
    
    try:
        response = requests.post(upload_endpoint, headers=headers, files=multipart_form_data)
        if response.status_code == 200:
            return {"status": "success", "message": "Successfully uploaded"}
        else:
            return {"status": "error", "message": f"Error: Received response code {response.status_code}"}
    except requests.exceptions.RequestException as e:
        return {"status": "error", "message": f"An error occurred: {e}"}

def pdf_upload(
    path: str = pdf_path,
    strategy: Optional[str] = 'smart',
    description: Optional[str] = "Tufts CS Handbook",
    session_id: Optional[str] = None
):
    if session_id is None:
        session_id = f"session_{int(time.time())}"
        
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
            
            response = upload(multipart_form_data)
            if response["status"] == "success":
                return {"status": "success", "session_id": session_id}
            return {"status": "error", "message": response["message"]}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def text_upload(
    text: str,
    strategy: Optional[str] = 'smart',
    description: Optional[str] = None,
    session_id: Optional[str] = None
):
    if session_id is None:
        session_id = f"session_{int(time.time())}"
        
    params = {
        'description': description,
        'session_id': session_id,
        'strategy': strategy
    }

    multipart_form_data = {
        'params': (None, json.dumps(params), 'application/json'),
        'text': (None, text, 'application/text')
    }

    response = upload(multipart_form_data)
    if isinstance(response, dict):
        response['session_id'] = session_id
    return response