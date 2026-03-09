from flask import Flask, request, jsonify
from PIL import Image
import requests
from io import BytesIO
import os
import uuid

app = Flask(__name__)

OUTPUT_DIR = "static"
os.makedirs(OUTPUT_DIR, exist_ok=True)


def download_image(url: str):
    response = requests.get(url)
    return Image.open(BytesIO(response.content)).convert("RGBA")


@app.route("/generate-mockup", methods=["POST"])
def generate_mockup():
    data = request.json

    shirt_url = data["shirt_image"]
    logo_url = data["logo_image"]

    x = int(data["placement"]["x"])
    y = int(data["placement"]["y"])
    w = int(data["placement"]["width"])
    h = int(data["placement"]["height"])

    shirt = download_image(shirt_url)
    logo = download_image(logo_url)

    logo.thumbnail((w, h))

    paste_x = x + (w - logo.width) // 2
    paste_y = y + (h - logo.height) // 2

    shirt.alpha_composite(logo, (paste_x, paste_y))

    filename = f"{uuid.uuid4().hex}.png"
    path = os.path.join(OUTPUT_DIR, filename)

    shirt.save(path)

    return jsonify({
        "mockup_url": f"http://127.0.0.1:10000/static/{filename}"
    })


if __name__ == "__main__":
    app.run(port=10000)