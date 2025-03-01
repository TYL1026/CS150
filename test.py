import requests

response_main = requests.get("https://shy-moyna-wendanj-b5959963.koyeb.app/")
print('Web Application Response:\n', response_main.text, '\n\n')


data = {"text":"talk about Policy on Parental Accommodation for Ph.D. Students at tufts"}
response_llmproxy = requests.post("https://shy-moyna-wendanj-b5959963.koyeb.app/query", json=data)
print('LLMProxy Response:\n', response_llmproxy.text)
