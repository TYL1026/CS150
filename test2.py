from llmproxy import generate, TuftsCSAdvisor

response = user_advisors[user_id]["advisor"].get_response(
            query=message, 
            lastk=current_lastk
        )