import ollama

# Sample realistic Spring Boot error log
SAMPLE_LOG = """
2026-10-27 10:15:32.401 ERROR 12345 --- [main] c.m.platform.service.UserService : Failed to process user registration
java.lang.NullPointerException: Cannot invoke "com.maersk.platform.repository.UserRepository.save(Object)" because "this.userRepository" is null
    at com.maersk.platform.service.UserService.registerUser(UserService.java:42)
    at com.maersk.platform.controller.UserController.createUser(UserController.java:28)
"""

def analyze_log(log_text: str):
    prompt = f"""
    You are an expert DevOps and Backend Platform Engineer. Analyze the following log snippet:

    LOG:
    {log_text}

    Provide your response strictly in the following format:
    1. ROOT CAUSE: (Short description of why it failed)
    2. SEVERITY: (CRITICAL / HIGH / MEDIUM / LOW)
    3. RECOMMENDED FIX: (Actionable steps or code change needed)
    """

    print("Sending log to local LLM (llama3.2)... Please wait.\n")
    
    response = ollama.chat(
        model='llama3.2',
        messages=[{'role': 'user', 'content': prompt}]
    )

    return response['message']['content']

if __name__ == "__main__":
    analysis = analyze_log(SAMPLE_LOG)
    print("=== LOGLENS AI ANALYSIS ===")
    print(analysis)
