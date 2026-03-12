from flask import Flask, request, jsonify, send_from_directory
from PIL import Image
from openai import OpenAI
import requests
from io import BytesIO
import os
import uuid
import io
import base64

app = Flask(__name__, static_folder="static")

OUTPUT_DIR = "static"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# OpenAI client (expects OPENAI_API_KEY in environment)
client = OpenAI()

BASE_REALISM_PROMPT = (
    "Make this sports shirt mock-up look more photorealistic. "
    "Keep the shirt shape, colour, background and sponsor logo exactly where they are. "
    "Do not change the logo design, wording, scale, or placement significantly. "
    "Add realistic fabric folds, subtle material texture, natural creases across the chest, "
    "realistic lighting, and make the printed sponsor look naturally applied to the shirt fabric."
)

SUBTLE_SUFFIX = (
    " Keep the result close to the original flat mock-up, "
    "with only mild realism and minimal visual change."
)

HIGH_SUFFIX = (
    " Increase the realism with stronger folds, fabric texture, lighting variation "
    "and print integration, while preserving the logo placement and shirt design as closely as possible."
)


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


def download_image(url: str) -> Image.Image:
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    return Image.open(BytesIO(response.content)).convert("RGBA")


def placement_to_pixels(
    shirt_width: int,
    shirt_height: int,
    placement_x: float,
    placement_y: float,
    placement_width: float,
    placement_height: float,
):
    """
    Supports either percentage placement values (0–100) or pixel values.
    """
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
        x = int(placement_x)
        y = int(placement_y)
        w = int(placement_width)
        h = int(placement_height)

    return x, y, w, h


def composite_logo_onto_shirt(
    shirt: Image.Image,
    logo: Image.Image,
    placement_x: float,
    placement_y: float,
    placement_width: float,
    placement_height: float,
) -> Image.Image:
    """
    Deterministic placement used by both flat and realistic flows.
    """
    shirt_w, shirt_h = shirt.size
    x, y, w, h = placement_to_pixels(
        shirt_w,
        shirt_h,
        placement_x,
        placement_y,
        placement_width,
        placement_height,
    )

    # Add padding so logo isn't flush to edges
    padding = int(min(w, h) * 0.08)
    padded_w = max(1, w - (padding * 2))
    padded_h = max(1, h - (padding * 2))

    logo_copy = logo.copy()
    logo_copy.thumbnail((padded_w, padded_h), Image.LANCZOS)

    paste_x = x + (w - logo_copy.width) // 2
    paste_y = y + (h - logo_copy.height) // 2

    composite = shirt.copy()
    composite.alpha_composite(logo_copy, (paste_x, paste_y))
    return composite


def image_to_png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf.read()


@app.route("/generate-mockup", methods=["POST"])
def generate_mockup():
    """
    Flat deterministic mock-up generation.
    Returns a public mockup_url served from this Render app.
    """
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

        flat_img = composite_logo_onto_shirt(
            shirt,
            logo,
            placement_x,
            placement_y,
            placement_width,
            placement_height,
        )

        filename = f"{uuid.uuid4().hex}.png"
        path = os.path.join(OUTPUT_DIR, filename)
        flat_img.save(path, format="PNG")

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


@app.route("/generate-realistic-mockup", methods=["POST"])
def generate_realistic_mockup():
    """
    Realistic mock-up generation:
    1. deterministic flat composite in memory
    2. OpenAI image edit for realism
    3. save final PNG to /static
    4. return mockup_url
    """
    try:
        data = request.get_json(force=True)

        shirt_image_url = data.get("shirt_image", "").strip()
        logo_image_url = data.get("logo_image", "").strip()
        placement = data.get("placement", {})
        realism_level = data.get("realism_level", "Subtle").strip()

        if not shirt_image_url:
            return jsonify({"success": False, "error": "shirt_image is required"}), 400
        if not logo_image_url:
            return jsonify({"success": False, "error": "logo_image is required"}), 400

        placement_x = float(placement.get("x", 30))
        placement_y = float(placement.get("y", 25))
        placement_width = float(placement.get("width", 40))
        placement_height = float(placement.get("height", 30))

        # Step 1: Download inputs
        shirt_img = download_image(shirt_image_url)
        logo_img = download_image(logo_image_url)

        # Step 2: Deterministic flat composite in memory
        composite_img = composite_logo_onto_shirt(
            shirt_img,
            logo_img,
            placement_x,
            placement_y,
            placement_width,
            placement_height,
        )

        composite_png_bytes = image_to_png_bytes(composite_img)

        # Step 3: Prompt
        if realism_level.lower() == "high":
            prompt = BASE_REALISM_PROMPT + HIGH_SUFFIX
        else:
            prompt = BASE_REALISM_PROMPT + SUBTLE_SUFFIX

        # Step 4: OpenAI image edit
        composite_file = io.BytesIO(composite_png_bytes)
        composite_file.name = "composite.png"

        response = client.images.edit(
            model="gpt-image-1.5",
            image=composite_file,
            prompt=prompt,
            n=1,
            size="1024x1024",
            output_format="png",
        )

        # Step 5: Decode returned base64 image
        image_data = response.data[0]

        if getattr(image_data, "b64_json", None):
            image_bytes = base64.b64decode(image_data.b64_json)
        else:
            return jsonify({
                "success": False,
                "error": "No base64 image data returned from OpenAI"
            }), 500

        # Step 6: Save final realistic PNG
        filename = f"realistic_{uuid.uuid4().hex}.png"
        filepath = os.path.join(OUTPUT_DIR, filename)

        with open(filepath, "wb") as f:
            f.write(image_bytes)

        # Step 7: Return public URL
        base_url = request.host_url.rstrip("/")
        mockup_url = f"{base_url}/static/{filename}"

        return jsonify({
            "success": True,
            "mockup_url": mockup_url
        })

    except requests.exceptions.RequestException as e:
        return jsonify({
            "success": False,
            "error": f"Image download failed: {str(e)}"
        }), 500
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)