import os
import json
import requests
import time
from typing import Optional

end_point = os.environ.get("endPoint")
api_key = os.environ.get("apiKey")
current_dir = os.path.dirname(os.path.abspath(__file__))
pdf_path = os.path.join(current_dir, "1.pdf")

def _upload_pdf():
    headers = {
        'x-api-key': api_key
    }
    
    session_id = f"session_{int(time.time())}"
    upload_endpoint = end_point.replace('/generate', '/upload')
    
    try:
        with open(pdf_path, 'rb') as pdf_file:
            multipart_form_data = {
                'params': (None, json.dumps({
                    'session_id': session_id,
                    'strategy': 'smart',
                    'description': 'Tufts CS Handbook'
                }), 'application/json'),
                'file': ('1.pdf', pdf_file, 'application/pdf')
            }
            
            response = requests.post(upload_endpoint, headers=headers, files=multipart_form_data)
            
            if response.status_code == 200:
                return session_id
            return None
    except:
        return None

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
    # If no specific session_id provided, try to upload PDF and use that session
    if session_id == 'GenericSession':
        session_id = _upload_pdf()
        # If upload fails, fall back to GenericSession
        if session_id is None:
            session_id = 'GenericSession'
            rag_usage = False  # Disable RAG if PDF upload failed
    
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
            return {'response': f"Error: Received response code {response.status_code}"}
    except requests.exceptions.RequestException as e:
        return {'response': f"An error occurred: {e}"}