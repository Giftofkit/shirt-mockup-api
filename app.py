from flask import Flask, request, jsonify, send_from_directory
from PIL import Image
import requests
from io import BytesIO
import os
import uuid

app = Flask(__name__, static_folder="static")

OUTPUT_DIR = "static"
os.makedirs(OUTPUT_DIR, exist_ok=True)


@app.route("/", methods=["GET"])
def root():
    return jsonify({"status": "mockup-api-running"}), 200


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


@app.route("/ping", methods=["GET"])
def ping():
    return jsonify({"status": "awake"}), 200


@app.route("/static/<path:filename>")
def serve_static(filename):
    return send_from_directory(OUTPUT_DIR, filename)


def download_image(url: str):
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    return Image.open(BytesIO(response.content)).convert("RGBA")


@app.route("/generate-mockup", methods=["POST"])
def generate_mockup():
    try:
        data = request.get_json()

        shirt_url = data["shirt_image"]
        logo_url = data["logo_image"]

        placement_x = float(data["placement"]["x"])
        placement_y = float(data["placement"]["y"])
        placement_width = float(data["placement"]["width"])
        placement_height = float(data["placement"]["height"])

        shirt = download_image(shirt_url)
        logo = download_image(logo_url)

        shirt_width, shirt_height = shirt.size

        # Support percentage placement values (0–100)
        if (
            0 <= placement_x <= 100 and
            0 <= placement_y <= 100 and
            0 < placement_width <= 100 and
            0 < placement_height <= 100
        ):
            x = int(shirt_width * (placement_x / 100))
            y = int(shirt_height * (placement_y / 100))
            w = int(shirt_width * (placement_width / 100))
            h = int(shirt_height * (placement_height / 100))
        else:
            # Otherwise assume pixel values
            x = int(placement_x)
            y = int(placement_y)
            w = int(placement_width)
            h = int(placement_height)

        # Add padding so logo isn't flush to edges
        padding = int(min(w, h) * 0.08)
        padded_w = max(1, w - (padding * 2))
        padded_h = max(1, h - (padding * 2))

        logo.thumbnail((padded_w, padded_h))

        paste_x = x + (w - logo.width) // 2
        paste_y = y + (h - logo.height) // 2

        shirt.alpha_composite(logo, (paste_x, paste_y))

        filename = f"{uuid.uuid4().hex}.png"
        path = os.path.join(OUTPUT_DIR, filename)
        shirt.save(path, format="PNG")

        base_url = request.host_url.rstrip("/")

        return jsonify({
            "success": True,
            "mockup_url": f"{base_url}/static/{filename}"
        })

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 400


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)