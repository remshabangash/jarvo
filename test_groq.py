from groq import Groq
from dotenv import load_dotenv
import os

load_dotenv()

key = os.getenv("GROQ_API_KEY")
print("Key loaded:", key[:10] if key else "NONE", "... length:", len(key) if key else 0)

client = Groq(api_key=key)

response = client.chat.completions.create(
    model="openai/gpt-oss-120b",
    messages=[
        {"role": "user", "content": "Salam, aap kaun hain?"}
    ]
)

print(response.choices[0].message.content.encode("utf-8", errors="replace").decode("utf-8"))