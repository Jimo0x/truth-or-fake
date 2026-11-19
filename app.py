"""Truth or Fake — serveur Flask."""
import os

from flask import Flask, jsonify, request, send_from_directory
from PIL import UnidentifiedImageError

from forensics import analyze

app = Flask(__name__, static_folder="static", static_url_path="")
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024


@app.get("/")
def index():
    return send_from_directory("static", "index.html")


@app.post("/api/analyze")
def api_analyze():
    f = request.files.get("image")
    if not f:
        return jsonify({"error": "Aucune image envoyée"}), 400
    try:
        return jsonify(analyze(f.read()))
    except (UnidentifiedImageError, OSError):
        return jsonify({"error": "Format d'image non reconnu"}), 400


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5002))
    print(f"Truth or Fake → http://127.0.0.1:{port}")
    app.run(host="127.0.0.1", port=port)
