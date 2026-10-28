import openai
import os
import json
import re
from dotenv import load_dotenv

# ✅ Load environment variables
load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")

# ✅ IPC Section → Urgency Score Mapping
IPC_URGENCY_MAP = {
    "302": 95,   # Murder
    "376": 90,   # Rape
    "307": 85,   # Attempt to murder
    "354": 78,   # Assault on woman
    "509": 60,   # Insulting modesty
    "379": 60,   # Theft
    "504": 55,   # Intentional insult
    "323": 50,   # Voluntarily causing hurt
    "143": 40,   # Unlawful assembly
    "34": 10     # Common intention
}

# ✅ Cognizable sections
COGNIZABLE_SECTIONS = {"302", "376", "307", "354"}

# ✅ Calculate max urgency score based on IPC codes
def compute_urgency(ipc_sections: list[str]) -> int:
    return max(IPC_URGENCY_MAP.get(code.strip(), 50) for code in ipc_sections) if ipc_sections else 50

# ✅ Determine if case is cognizable
def is_cognizable_predicted(ipc_sections: dict) -> bool:
    return any(code in COGNIZABLE_SECTIONS for code in ipc_sections.keys())

# ✅ Extract valid JSON from GPT response using regex
def extract_json(text: str) -> str:
    match = re.search(r'\{[\s\S]+\}', text)
    if match:
        return match.group()
    return "{}"

# ✅ Main function: GPT-powered IPC section extractor and urgency calculator
def get_ai_assessment(incident_summary: str):
    prompt = f"""
You are SmartCop AI, an expert legal assistant trained in the Indian Penal Code (IPC).

Your job is to analyze detailed incident reports and extract relevant IPC sections and their legal descriptions.
Return ONLY in this strict JSON format:
{{
  "ipc_sections": {{
    "IPC_CODE": "Section description"
  }}
}}

### Examples:

Example 1:
Incident:
"On the evening of April 10th, a 45-year-old man named Rajesh Kumar was attacked with a knife outside his grocery store in Bhopal. The attacker, later identified as a neighbor, had a long-standing land dispute with Rajesh. The attack was witnessed by nearby shopkeepers and captured on CCTV. Rajesh sustained severe injuries and was rushed to the hospital, where he succumbed to his wounds."
Response:
{{
  "ipc_sections": {{
    "302": "Murder",
    "34": "Acts done by several persons in furtherance of common intention"
  }}
}}

Example 2:
Incident:
"Priya, a 24-year-old software engineer, was returning home from work when a group of three men on bikes began following her. They made inappropriate comments, blocked her path, and one of them tried to grab her bag. She ran into a nearby shop and called the police. The incident caused her significant distress and fear for her safety."
Response:
{{
  "ipc_sections": {{
    "354": "Assault or criminal force to woman with intent to outrage her modesty",
    "509": "Word, gesture or act intended to insult the modesty of a woman"
  }}
}}

Example 3:
Incident:
"Two teenagers were seen stealing a parked motorcycle outside a supermarket in broad daylight. CCTV footage showed them cutting the lock and riding away together. The owner filed a complaint with the local police, and the footage was submitted as evidence. Both suspects were later identified as residents of a nearby colony."
Response:
{{
  "ipc_sections": {{
    "379": "Theft",
    "34": "Acts done by several persons in furtherance of common intention"
  }}
}}

Now analyze this new incident:
\"\"\"{incident_summary}\"\"\"
Respond with valid JSON only. No extra text.
"""

    try:
        # ✅ Send prompt to GPT
        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "You are an expert legal assistant AI trained on IPC laws."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3
        )

        content = response['choices'][0]['message']['content']

        # ✅ Extract and parse JSON
        json_text = extract_json(content)
        parsed = json.loads(json_text)
        ipc_sections = parsed.get("ipc_sections", {})

        # ✅ Predict cognizable or not
        is_cognizable = is_cognizable_predicted(ipc_sections)

        # ✅ Final response
        if is_cognizable:
            urgency_score = compute_urgency(list(ipc_sections.keys()))
            return {
                "is_cognizable": True,
                "AI_urgency_score": urgency_score,
                "ipc_sections": ipc_sections
            }
        else:
            return {
                "is_cognizable": False,
                "message": "This is a non-cognizable offence. It will be recorded as a General Diary (GD) entry.",
                "ipc_sections": ipc_sections
            }

    except Exception as e:
        return {
            "is_cognizable": False,
            "message": "An error occurred while analyzing the case. Defaulting to non-cognizable GD entry.",
            "ipc_sections": {
                "504": "Intentional insult with intent to provoke breach of peace"
            }
        }