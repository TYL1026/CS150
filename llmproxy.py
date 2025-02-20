import os
import json
import requests
import time
from typing import Dict, Optional, Union, Any

current_dir = os.path.dirname(os.path.abspath(__file__))
pdf_path = os.path.join(current_dir, "1.pdf")

end_point = os.environ.get("endPoint")
api_key = os.environ.get("apiKey")

def generate(
    model: str,
    system: str,
    query: str,
    temperature: Optional[float] = None,
    lastk: Optional[int] = None,
    session_id: Optional[str] = None,
    rag_usage: bool = False,
    rag_threshold: float = 0.5,
    rag_k: int = 0
) -> Dict[str, Any]:
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
        'rag_usage': rag_usage,
        'rag_threshold': rag_threshold,
        'rag_k': rag_k
    }
    
    try:
        response = requests.post(end_point, headers=headers, json=request)
        if response.status_code == 200:
            res = json.loads(response.text)
            return {
                'response': res['result'],
                'rag_context': res.get('rag_context'),
                'error': None
            }
        elif response.status_code == 401:
            return {
                'response': None,
                'rag_context': None,
                'error': "Authentication failed. Please check your API key."
            }
        elif response.status_code == 403:
            return {
                'response': None,
                'rag_context': None,
                'error': "Access forbidden. Please ensure you have the correct permissions."
            }
        else:
            return {
                'response': None,
                'rag_context': None,
                'error': f"Error: Received response code {response.status_code} - {response.text}"
            }
    except requests.exceptions.RequestException as e:
        return {
            'response': None,
            'rag_context': None,
            'error': f"An error occurred: {str(e)}"
        }

def pdf_upload(path: str = pdf_path, strategy: str = 'smart') -> Dict:
    if not os.path.exists(path):
        return {"error": f"PDF file not found at path: {path}"}
    
    headers = {
        'x-api-key': api_key
    }
    
    session_id = f"session_{int(time.time())}"
    
    try:
        with open(path, 'rb') as pdf_file:
            multipart_form_data = {
                'params': (None, json.dumps({
                    'session_id': session_id,
                    'strategy': strategy
                }), 'application/json'),
                'file': ('1.pdf', pdf_file, 'application/pdf')
            }
            
            upload_endpoint = end_point.replace('/generate', '/upload')
            response = requests.post(upload_endpoint, headers=headers, files=multipart_form_data)
            
            if response.status_code == 200:
                return {
                    "status": "success",
                    "message": "PDF uploaded successfully",
                    "session_id": session_id
                }
            else:
                return {
                    "error": f"Upload failed with status code {response.status_code}: {response.text}",
                    "session_id": session_id
                }
                
    except IOError as e:
        return {"error": f"Error reading PDF file: {str(e)}"}
    except requests.exceptions.RequestException as e:
        return {"error": f"Upload error: {str(e)}"}

def text_upload(
    text: str,
    strategy: Optional[str] = 'smart',
    description: Optional[str] = None,
    session_id: Optional[str] = None
) -> Dict[str, str]:
    headers = {
        'x-api-key': api_key
    }
    
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
    
    try:
        upload_endpoint = end_point.replace('/generate', '/upload')
        response = requests.post(upload_endpoint, headers=headers, files=multipart_form_data)
        
        if response.status_code == 200:
            return {
                'status': "Successfully uploaded text content",
                'session_id': session_id,
                'error': None
            }
        else:
            return {
                'status': None,
                'session_id': session_id,
                'error': f"Error: Received response code {response.status_code}"
            }
    except requests.exceptions.RequestException as e:
        return {
            'status': None,
            'session_id': session_id,
            'error': f"An error occurred: {str(e)}"
        }

def main():
    print("Starting PDF upload...")
    upload_result = pdf_upload()
    
    if "error" in upload_result:
        print(f"Upload Error: {upload_result['error']}")
        return
        
    print(f"Upload Success: {upload_result['message']}")
    session_id = upload_result['session_id']
    print(f"Session ID: {session_id}")
    
    print("\nTesting generate function...")
    system_prompt = "You are a helpful assistant."
    test_query = "Hello, how are you?"
    
    response = generate(
        model="claude-3-haiku-20240307",
        system=system_prompt,
        query=test_query,
        session_id=session_id,
        rag_usage=True,
        rag_threshold=0.7,
        rag_k=3
    )
    
    if response.get('error'):
        print(f"Generate Error: {response['error']}")
    else:
        print("\nResponse:", response['response'])
        if response.get('rag_context'):
            print("\nRAG Context:", response['rag_context'])

if __name__ == "__main__":
    main()