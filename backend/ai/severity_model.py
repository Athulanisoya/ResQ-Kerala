import os
import re
import joblib

MODEL_PATH = os.path.join(
    os.path.dirname(__file__),
    "pipeline.joblib"
)
pipeline = joblib.load(MODEL_PATH)

def clean_text(text):
    text = str(text)
    text = text.lower()
    text = re.sub(r"\s+", " ", text)
    text = text.strip()
    return text

def predict_severity(message):
    cleaned_message = clean_text(message)

    prediction = pipeline.predict([cleaned_message])

    return str(prediction[0])