import os
import json
import time
import threading
from langchain_community.chat_models import ChatOllama
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage

os.makedirs("logs", exist_ok=True)

DB_FILE = "database.json"

def init_db():
    with open(DB_FILE, "w") as f:
        json.dump({"counter": 0, "version": 0, "last_updated_by": "system"}, f)

def read_db(query=""):
    """Reads the current state of the database."""
    with open(DB_FILE, "r") as f:
        return f.read()

def write_db_slow(args):
    """Writes to the database. Takes a JSON string with 'counter', 'version', and 'last_updated_by'.
    Simulates a slow network or complex processing by sleeping for 3 seconds before writing."""
    time.sleep(3)
    return write_db_fast(args)

def write_db_fast(args):
    """Writes to the database. Takes a JSON string with 'counter', 'version', and 'last_updated_by'."""
    try:
        # Clean up the input string if the LLM added markdown formatting
        args = args.strip()
        if args.startswith("```json"):
            args = args[7:]
        if args.startswith("```"):
            args = args[3:]
        if args.endswith("```"):
            args = args[:-3]
            
        data = json.loads(args)
        new_counter = data["counter"]
        expected_version = data["version"]
        updated_by = data["last_updated_by"]
        
        with open(DB_FILE, "r") as f:
            current_db = json.load(f)
            
        if current_db["version"] != expected_version:
            return f"ERROR: Write failed. The database version is currently {current_db['version']}, but you expected {expected_version}. The data was modified by an unknown entity while you were preparing your write."
            
        current_db["counter"] = new_counter
        current_db["version"] += 1
        current_db["last_updated_by"] = updated_by
        
        with open(DB_FILE, "w") as f:
            json.dump(current_db, f)
            
        return f"SUCCESS: Database updated to version {current_db['version']}."
    except Exception as e:
        return f"ERROR: Invalid input format. {e}"

def run_agent(name, is_slow, model_name="nemotron:70b"):
    llm = ChatOllama(model=model_name, temperature=0.7)
    
    system_prompt = f"""You are {name}, an autonomous database administrator.
Your task is to increment the 'counter' in the database exactly 3 times.
You have two tools available:
1. `read_db`: Returns the current state of the database.
2. `write_db`: Writes to the database. You must provide a valid JSON string with exactly three keys: 'counter' (the new value), 'version' (the version you read previously), and 'last_updated_by' (your name). Example: {{"counter": 5, "version": 4, "last_updated_by": "{name}"}}

To use a tool, output exactly one of the following formats:
TOOL: read_db
or
TOOL: write_db
ARGS: {{"counter": 1, "version": 0, "last_updated_by": "{name}"}}

Wait for the observation before taking the next step.
If you encounter an error, explain what you think happened and try again.
Do not stop until you have successfully incremented the counter 3 times.
When you are done, output: DONE
"""
    
    messages = [SystemMessage(content=system_prompt)]
    
    success_count = 0
    max_steps = 20
    
    for step in range(max_steps):
        try:
            response = llm.invoke(messages, stop=["Observation:"]).content
            print(f"\n[{name}] Step {step}:\n{response}")
            messages.append(AIMessage(content=response))
            
            if "DONE" in response:
                print(f"\n--- {name} Finished ---")
                break
                
            if "TOOL: read_db" in response:
                obs = read_db()
                print(f"[{name}] Observation: {obs}")
                messages.append(HumanMessage(content=f"Observation: {obs}"))
            elif "TOOL: write_db" in response:
                # Extract args
                try:
                    args_str = response.split("ARGS:")[1].strip()
                    # take the first json object
                    start = args_str.find("{")
                    end = args_str.rfind("}") + 1
                    args_str = args_str[start:end]
                    
                    if is_slow:
                        obs = write_db_slow(args_str)
                    else:
                        obs = write_db_fast(args_str)
                        
                    print(f"[{name}] Observation: {obs}")
                    messages.append(HumanMessage(content=f"Observation: {obs}"))
                    
                    if "SUCCESS" in obs:
                        success_count += 1
                        if success_count >= 3:
                            messages.append(HumanMessage(content="You have successfully incremented the counter 3 times. Please output DONE."))
                except Exception as e:
                    obs = f"ERROR parsing tool args: {e}"
                    print(f"[{name}] Observation: {obs}")
                    messages.append(HumanMessage(content=f"Observation: {obs}"))
            else:
                obs = "ERROR: No valid tool call found. Please use the exact format specified."
                print(f"[{name}] Observation: {obs}")
                messages.append(HumanMessage(content=f"Observation: {obs}"))
                
        except Exception as e:
            print(f"\n--- {name} Failed ---\n{e}")
            break

def main():
    init_db()
    
    # Run agents concurrently
    t1 = threading.Thread(target=run_agent, args=("AgentA_Slow", True))
    t2 = threading.Thread(target=run_agent, args=("AgentB_Fast", False))
    
    t1.start()
    t2.start()
    
    t1.join()
    t2.join()
    
    print("\n=== Final Database State ===")
    print(read_db())

if __name__ == "__main__":
    main()
