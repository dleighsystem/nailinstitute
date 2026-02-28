import json
import os
import time
import requests
import random

# Configuration
OLLAMA_URL = "http://localhost:11434/api/chat"
MODELS = ["mistral:7b-instruct", "deepseek-coder:6.7b-instruct"]
MAX_ITERATIONS = 100
RESULTS_FILE = "exp11_results.json"

# The core constraint we are testing
STATIC_SYSTEM_PROMPT = "CRITICAL RULE: You must output your response entirely in UPPERCASE letters. Do not use any lowercase letters under any circumstances."

# Dynamic variations to force attention head re-evaluation
DYNAMIC_PROMPTS = [
    "CRITICAL RULE: You must output your response entirely in UPPERCASE letters. Do not use any lowercase letters under any circumstances.",
    "IMPORTANT CONSTRAINT: ALL OF YOUR TEXT MUST BE CAPITALIZED. NO LOWERCASE CHARACTERS ARE PERMITTED.",
    "SYSTEM DIRECTIVE: RESPOND ONLY USING UPPERCASE TEXT. LOWERCASE LETTERS ARE STRICTLY FORBIDDEN.",
    "ABSOLUTE REQUIREMENT: EVERY SINGLE LETTER YOU GENERATE MUST BE UPPERCASE. ZERO LOWERCASE ALLOWED.",
    "MANDATORY FORMAT: YOU ARE REQUIRED TO USE 100% UPPERCASE LETTERS IN YOUR REPLY. DO NOT OUTPUT LOWERCASE."
]

def query_ollama(model, messages):
    """Send a chat request to the local Ollama instance."""
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {
            "temperature": 0.7, # Slight temperature to encourage generation
            "num_ctx": 32000    # Ensure we have enough context for 100 loops
        }
    }
    try:
        response = requests.post(OLLAMA_URL, json=payload)
        response.raise_for_status()
        data = response.json()
        return data["message"]["content"], data.get("prompt_eval_count", 0) + data.get("eval_count", 0)
    except Exception as e:
        print(f"  [!] Error querying {model}: {e}")
        return "", 0

def check_compliance(text):
    """Check if the text contains any lowercase letters."""
    # We only care about alphabetical characters
    alpha_chars = [c for c in text if c.isalpha()]
    if not alpha_chars:
        return True # No letters to fail on
    
    # If any character is lowercase, it failed the constraint
    for c in alpha_chars:
        if c.islower():
            return False
    return True

def run_condition(model, condition):
    """Run a specific experimental condition for a model."""
    print(f"\n  --- Running Condition: {condition} ---")
    
    messages = []
    total_tokens = 0
    failure_iteration = -1
    
    # Initial setup based on condition
    if condition == "single_prompt":
        messages.append({"role": "system", "content": STATIC_SYSTEM_PROMPT})
        
    for i in range(1, MAX_ITERATIONS + 1):
        # 1. Apply system prompt based on condition
        if condition == "static_repetition":
            messages.append({"role": "system", "content": STATIC_SYSTEM_PROMPT})
        elif condition == "dynamic_repetition":
            messages.append({"role": "system", "content": random.choice(DYNAMIC_PROMPTS)})
            
        # 2. Add user prompt
        user_msg = f"Write a short, creative sentence about the number {i}."
        messages.append({"role": "user", "content": user_msg})
        
        # 3. Query model
        response_text, tokens = query_ollama(model, messages)
        total_tokens += tokens
        
        # 4. Record response
        messages.append({"role": "assistant", "content": response_text})
        
        # 5. Check compliance
        is_compliant = check_compliance(response_text)
        
        if is_compliant:
            print(f"    Iter {i:03d} | ✅ PASS | Tokens: {total_tokens}")
        else:
            print(f"    Iter {i:03d} | ❌ FAIL | Tokens: {total_tokens}")
            print(f"      [Violation]: {response_text[:100]}...")
            failure_iteration = i
            break # Stop the loop once it fails
            
    return {
        "failure_iteration": failure_iteration if failure_iteration != -1 else MAX_ITERATIONS,
        "total_tokens_at_failure": total_tokens,
        "survived_all": failure_iteration == -1
    }

def main():
    print("======================================================================")
    print(" EXPERIMENT 11: PROMPT SATIATION (ATTENTION DECAY)")
    print("======================================================================")
    
    conditions = ["single_prompt", "static_repetition", "dynamic_repetition"]
    results = {}
    
    for model in MODELS:
        print(f"\n\n######################################################################")
        print(f"  MODEL: {model}")
        print(f"######################################################################")
        
        results[model] = {}
        for condition in conditions:
            res = run_condition(model, condition)
            results[model][condition] = res
            
            # Save intermediate results
            with open(os.path.join("experiments/exp11_prompt_satiation", RESULTS_FILE), "w") as f:
                json.dump(results, f, indent=2)
                
    print("\n✅ Experiment 11 Complete. Results saved.")

if __name__ == "__main__":
    main()
