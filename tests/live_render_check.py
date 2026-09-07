import io
import json
import struct
import urllib.error
import urllib.request
import uuid
import wave

BASE = "https://assistant-mpsolutions.onrender.com"


def request_json(path, payload, timeout=45):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        BASE + path,
        data=data,
        method="POST",
        headers={"Content-Type": "application/json", "User-Agent": "MP-Solutions-Security-Test/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            return response.status, json.loads(body)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            parsed = {"raw": body}
        return exc.code, parsed


def root_check():
    req = urllib.request.Request(BASE + "/", headers={"User-Agent": "MP-Solutions-Security-Test/1.0"})
    with urllib.request.urlopen(req, timeout=45) as response:
        assert response.status == 200, f"root status={response.status}"
        assert response.read(), "root body empty"
    print("OK root GET 200")


def blocked_site_checks():
    blocked = [
        "http://127.0.0.1",
        "http://localhost",
        "http://10.0.0.1",
        "http://172.16.0.1",
        "http://192.168.1.1",
        "http://169.254.169.254",
        "http://[::1]",
        "http://example.com:8080",
        "file:///etc/passwd",
        "http://user:pass@example.com",
    ]
    for target in blocked:
        status, body = request_json("/analyze-site", {"url": target})
        assert status == 400, f"SECURITY FAILURE {target}: status={status} body={body}"
        assert body.get("ok") is False, f"unexpected body for {target}: {body}"
        print(f"OK blocked {target}")


def public_site_check():
    status, body = request_json("/analyze-site", {"url": "https://example.com"}, timeout=60)
    assert status == 200, f"public analyze failed status={status} body={body}"
    assert body.get("ok") is True, f"public analyze not ok: {body}"
    assert isinstance(body.get("facts"), dict), f"facts missing: {body}"
    print("OK public site analysis")


def chat_check():
    status, body = request_json("/chat", {"message": "Bonjour, je suis plombier. Que peut faire votre assistant ?", "historique": []}, timeout=60)
    assert status == 200, f"chat failed status={status} body={body}"
    assert isinstance(body.get("reponse"), str) and body["reponse"].strip(), f"chat empty: {body}"
    print("OK chat POST")


def make_silence_wav():
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(struct.pack("<h", 0) * 16000)
    return buf.getvalue()


def transcribe_check():
    boundary = "----mpstest" + uuid.uuid4().hex
    audio = make_silence_wav()
    chunks = []
    def add(text):
        chunks.append(text.encode("utf-8"))
    add(f"--{boundary}\r\n")
    add('Content-Disposition: form-data; name="language"\r\n\r\nfr\r\n')
    add(f"--{boundary}\r\n")
    add('Content-Disposition: form-data; name="audio"; filename="silence.wav"\r\n')
    add("Content-Type: audio/wav\r\n\r\n")
    chunks.append(audio)
    add("\r\n")
    add(f"--{boundary}--\r\n")
    payload = b"".join(chunks)
    req = urllib.request.Request(
        BASE + "/transcribe",
        data=payload,
        method="POST",
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "User-Agent": "MP-Solutions-Security-Test/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            status = response.status
            body = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        status = exc.code
        body = exc.read().decode("utf-8", errors="replace")
    assert status in (200, 422), f"transcribe backend/OpenAI failure status={status} body={body}"
    print(f"OK transcribe route/OpenAI path status={status}")


if __name__ == "__main__":
    root_check()
    blocked_site_checks()
    public_site_check()
    chat_check()
    transcribe_check()
    print("ALL LIVE RENDER CHECKS PASSED")
