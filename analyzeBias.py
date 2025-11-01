from fastapi import FastAPI, Request
from transformers import RobertaTokenizer, AutoModelForSequenceClassification, pipeline
import re

app = FastAPI()

MODEL_NAME = "matous-volf/political-leaning-politics"
MAX_TOKENS = 512

print("Loading model...")
tokenizer = RobertaTokenizer.from_pretrained("roberta-base")
model = AutoModelForSequenceClassification.from_pretrained(MODEL_NAME)
classifier = pipeline("text-classification", model=model, tokenizer=tokenizer)
print("Model loaded successfully!")

label_map = {"LABEL_0": -1, "LABEL_1": 0, "LABEL_2": 1}

def chunk_text(text, max_tokens=MAX_TOKENS):
    sentences = re.split(r'(?<=[.!?]) +', text.strip())
    chunks, current_chunk, current_len = [], "", 0
    for s in sentences:
        slen = len(tokenizer.encode(s, add_special_tokens=False))
        if current_len + slen > max_tokens:
            if current_chunk:
                chunks.append(current_chunk.strip())
            current_chunk, current_len = s, slen
        else:
            current_chunk += " " + s
            current_len += slen
    if current_chunk:
        chunks.append(current_chunk.strip())
    return chunks

@app.post("/analyze")
async def analyze(request: Request):
    data = await request.json()
    text = data.get("text", "")
    if not text:
        return {"error": "Missing 'text' field."}
    
    chunks = chunk_text(text)
    total_weighted, total_tokens = 0, 0

    for chunk in chunks:
        result = classifier(chunk)[0]
        label, score = result["label"], result["score"]
        tokens = len(tokenizer.encode(chunk, add_special_tokens=False))
        total_weighted += label_map[label] * score * tokens
        total_tokens += tokens

    final_score = total_weighted / total_tokens if total_tokens else 0
    return {"bias_score": round(final_score, 3), "chunks": len(chunks)}
