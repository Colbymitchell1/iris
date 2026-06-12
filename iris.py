#!/usr/bin/env python3
"""
Iris - optical file transfer between two laptops.
No network connection between machines required. One machine displays
a looping sequence of QR codes; the other reads them via webcam and
reassembles the file.

Run on both machines:
    python3 iris.py

Then open http://127.0.0.1:5000 and pick Send or Receive.
"""

import base64
import os
import re
import webbrowser
import threading

from flask import Flask, request, jsonify, render_template, send_from_directory
import qrcode
import qrcode.constants
import io

# --- Config ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INBOX_DIR = os.path.join(BASE_DIR, "inbox")
CHUNK_SIZE = 300  # base64 characters per QR frame

os.makedirs(INBOX_DIR, exist_ok=True)

app = Flask(__name__)


def make_qr_data_url(text: str) -> str:
    """Generate a QR code PNG for `text`, return as a data: URL."""
    qr = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=8,
        border=2,
    )
    qr.add_data(text)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{b64}"


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/static/<path:filename>")
def static_files(filename):
    return send_from_directory(os.path.join(BASE_DIR, "static"), filename)


@app.route("/api/prepare", methods=["POST"])
def prepare():
    """Take an uploaded file, chunk it, and return a list of QR frame images."""
    if "file" not in request.files:
        return jsonify({"error": "no file"}), 400

    f = request.files["file"]
    filename = f.filename
    data = f.read()

    if not data:
        return jsonify({"error": "empty file"}), 400

    b64_data = base64.b64encode(data).decode("ascii")
    chunks = [b64_data[i:i + CHUNK_SIZE] for i in range(0, len(b64_data), CHUNK_SIZE)]
    total = len(chunks)

    file_id = base64.b32encode(os.urandom(4)).decode("ascii").rstrip("=").lower()

    frames = []

    # Frame 0: metadata
    meta_payload = f"IRISMETA|{file_id}|{total}|{filename}"
    frames.append(make_qr_data_url(meta_payload))

    # Frames 1..N: data
    for idx, chunk in enumerate(chunks):
        payload = f"IRISDATA|{file_id}|{idx}|{chunk}"
        frames.append(make_qr_data_url(payload))

    return jsonify({
        "file_id": file_id,
        "filename": filename,
        "total": total,
        "frames": frames,
    })


@app.route("/api/save", methods=["POST"])
def save():
    """Receive a reassembled file (filename + base64 content) and write it to inbox/."""
    payload = request.get_json(force=True)
    filename = payload.get("filename")
    b64_data = payload.get("data")

    if not filename or b64_data is None:
        return jsonify({"error": "missing filename or data"}), 400

    # Sanitize filename - strip path components, keep it inside inbox/
    safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", os.path.basename(filename))
    if not safe_name:
        safe_name = "received_file"

    dest = os.path.join(INBOX_DIR, safe_name)

    # Avoid overwriting existing files
    base, ext = os.path.splitext(dest)
    counter = 1
    while os.path.exists(dest):
        dest = f"{base}_{counter}{ext}"
        counter += 1

    try:
        raw = base64.b64decode(b64_data)
    except Exception as e:
        return jsonify({"error": f"bad base64: {e}"}), 400

    with open(dest, "wb") as out:
        out.write(raw)

    return jsonify({"status": "ok", "path": dest})


def open_browser():
    webbrowser.open("http://127.0.0.1:5000")


if __name__ == "__main__":
    threading.Timer(1.0, open_browser).start()
    app.run(host="127.0.0.1", port=5000, debug=False)
