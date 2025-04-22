from llmproxy import pdf_upload

def handbook_upload(user_id):
    try:
        all_references = ["cs_handbook.pdf", "soe-grad-handbook.pdf", "filtered_grad_courses.pdf"]
        for reference in all_references:
            response = pdf_upload(
                path = f'resources/{reference}',
                session_id = 'cs-advising-handbooks-v5-' + user_id,
                strategy = 'smart'
            )
            print("✅ " + reference + " is successfully loaded")

    except Exception as e:
        print(f"❌ Error uploading handbooks: {str(e)}")

