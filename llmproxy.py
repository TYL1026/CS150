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

    try:
        response = requests.post(end_point, headers=headers, json=request)
        if response.status_code == 200:
            res = json.loads(response.text)
            return {'response': res['result'], 'rag_context': res.get('rag_context')}
        else:
            return {'response': f"Error: Received response code {response.status_code}"}
    except requests.exceptions.RequestException as e:
        return {'response': f"An error occurred: {e}"}

def upload(multipart_form_data):
    headers = {
        'x-api-key': api_key
    }

    # Get upload endpoint by replacing last part of path
    parts = end_point.split('/')
    upload_endpoint = '/'.join(parts[:-1] + ['upload'])

    try:
        response = requests.post(upload_endpoint, headers=headers, files=multipart_form_data)
        if response.status_code == 200:
            return "Successfully uploaded. It may take a short while for the document to be added to your context"
        else:
            return f"Error: Received response code {response.status_code}"
    except requests.exceptions.RequestException as e:
        return f"An error occurred: {e}"

def pdf_upload(
    path: str,
    strategy: str | None = 'smart',
    description: str | None = None,
    session_id: str | None = None
):
    params = {
        'description': description,
        'session_id': session_id,
        'strategy': strategy
    }

    with open(path, 'rb') as pdf_file:
        multipart_form_data = {
            'params': (None, json.dumps(params), 'application/json'),
            'file': ('1.pdf', pdf_file, 'application/pdf')
        }

        response = upload(multipart_form_data)
        return response

def text_upload(
    text: str,
    strategy: str | None = 'smart',
    description: str | None = None,
    session_id: str | None = None
):
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
    return response