#!/usr/bin/env python3
"""Deploy ~/workspace/pages-bundle to the Cloudflare Pages project
bond-credit-monitor through the direct upload API.

Account level calls go through the custom.cloudflare connector
credential. The short lived upload JWT returned by the API is used
directly for the asset endpoints, as the API intends.
"""
import base64
import hashlib  # noqa: F401 (kept for ad hoc checks)
import json
import mimetypes
import sys
import time
import urllib.request
import uuid
from pathlib import Path

sys.path.insert(0, "/opt/muse/skills/custom-connector-setup/bin")
from dynamic_credentials import add_surrogate_to_request

ACCOUNT_ID = "4594aba4f2331f4d77a93db5a3906794"
PROJECT = "bond-credit-monitor"
BASE = "https://api.cloudflare.com/client/v4"
BUNDLE = Path("/home/hatch/workspace/pages-bundle")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        raise RuntimeError("redirect refused")


def open_req(req, timeout=300):
    opener = urllib.request.build_opener(NoRedirect())
    try:
        with opener.open(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def account_call(method, path, data=None, content_type=None):
    req = urllib.request.Request(BASE + path, method=method, data=data)
    if content_type:
        req.add_header("Content-Type", content_type)
    add_surrogate_to_request(req, "custom.cloudflare",
                             allowed_hosts=["api.cloudflare.com"])
    return open_req(req)


def jwt_call(method, path, jwt, data=None, content_type=None):
    req = urllib.request.Request(BASE + path, method=method, data=data)
    req.add_header("Authorization", f"Bearer {jwt}")
    if content_type:
        req.add_header("Content-Type", content_type)
    return open_req(req)


def multipart(fields):
    """fields: list of (name, value_bytes, content_type or None[, filename])."""
    boundary = "----cfpages" + uuid.uuid4().hex
    out = []
    for field in fields:
        name, value, ctype = field[0], field[1], field[2]
        filename = field[3] if len(field) > 3 else None
        out.append(f"--{boundary}\r\n".encode())
        disp = f'Content-Disposition: form-data; name="{name}"'
        if filename:
            disp += f'; filename="{filename}"'
        out.append((disp + "\r\n").encode())
        if ctype:
            out.append(f"Content-Type: {ctype}\r\n".encode())
        out.append(b"\r\n")
        out.append(value)
        out.append(b"\r\n")
    out.append(f"--{boundary}--\r\n".encode())
    return b"".join(out), f"multipart/form-data; boundary={boundary}"


def file_hash(data: bytes, rel: str) -> str:
    # Mirrors wrangler hashFile: blake3 of the base64 text plus the
    # extension without a dot, first 32 hex characters.
    from blake3 import blake3
    name = rel.rsplit("/", 1)[-1]
    ext = name.rsplit(".", 1)[-1] if "." in name else ""
    if ext == name:
        ext = ""
    digest = blake3(base64.b64encode(data) + ext.encode()).hexdigest()
    return digest[:32]


def main():
    skip_top = {"_worker.js", "_headers", "_redirects", "_routes.json"}
    files = {}
    for path in sorted(BUNDLE.rglob("*")):
        if path.is_file():
            rel = "/" + str(path.relative_to(BUNDLE))
            top = rel.split("/")[1]
            if top in skip_top or top == "functions":
                continue
            files[rel] = path
    worker_path = BUNDLE / "_worker.js"
    worker_js = worker_path.read_bytes() if worker_path.is_file() else None
    manifest = {}
    blobs = {}
    for rel, path in files.items():
        data = path.read_bytes()
        h = file_hash(data, rel)
        manifest[rel] = h
        blobs[h] = (rel, data)
    print(f"files={len(files)} unique_blobs={len(blobs)}")

    status, body = account_call(
        "GET", f"/accounts/{ACCOUNT_ID}/pages/projects/{PROJECT}/upload-token")
    payload = json.loads(body)
    if status != 200 or not payload.get("success"):
        print("upload-token failed:", status, body[:300])
        sys.exit(1)
    jwt = payload["result"]["jwt"]
    print("upload token acquired")

    status, body = jwt_call(
        "POST", "/pages/assets/check-missing", jwt,
        data=json.dumps({"hashes": list(blobs)}).encode(),
        content_type="application/json")
    payload = json.loads(body)
    if status != 200 or not payload.get("success"):
        print("check-missing failed:", status, body[:300])
        sys.exit(1)
    result = payload["result"]
    missing = result["missing"] if isinstance(result, dict) else result
    print(f"missing={len(missing)}")

    batch, batch_bytes = [], 0
    batches = []
    for h in missing:
        rel, data = blobs[h]
        batch.append((h, rel, data))
        batch_bytes += len(data)
        if len(batch) >= 100 or batch_bytes >= 8_000_000:
            batches.append(batch)
            batch, batch_bytes = [], 0
    if batch:
        batches.append(batch)
    for i, batch in enumerate(batches, 1):
        entries = []
        for h, rel, data in batch:
            ctype = mimetypes.guess_type(rel)[0] or "application/octet-stream"
            entries.append({
                "key": h,
                "value": base64.b64encode(data).decode(),
                "metadata": {"contentType": ctype},
                "base64": True,
            })
        status, body = jwt_call(
            "POST", "/pages/assets/upload", jwt,
            data=json.dumps(entries).encode(),
            content_type="application/json")
        payload = json.loads(body) if body else {}
        if status != 200 or not payload.get("success"):
            print(f"upload batch {i} failed:", status, body[:300])
            sys.exit(1)
        print(f"uploaded batch {i}/{len(batches)} ({len(batch)} files)")

    status, body = jwt_call(
        "POST", "/pages/assets/upsert-hashes", jwt,
        data=json.dumps({"hashes": list(blobs)}).encode(),
        content_type="application/json")
    print("upsert-hashes:", status)

    fields = [("manifest", json.dumps(manifest).encode(), None),
              ("branch", b"main", None)]
    if worker_js is not None:
        inner, inner_ctype = multipart([
            ("metadata",
             json.dumps({"main_module": "_worker.js"}).encode(),
             "application/json"),
            ("_worker.js", worker_js, "application/javascript+module",
             "_worker.js"),
        ])
        fields.append(("_worker.bundle", inner, inner_ctype,
                       "_worker.bundle"))
        print("worker bundle attached:", len(worker_js), "bytes")
    body_bytes, ctype_header = multipart(fields)
    status, body = account_call(
        "POST", f"/accounts/{ACCOUNT_ID}/pages/projects/{PROJECT}/deployments",
        data=body_bytes, content_type=ctype_header)
    payload = json.loads(body) if body else {}
    if status != 200 or not payload.get("success"):
        print("create deployment failed:", status, body[:500])
        sys.exit(1)
    dep = payload["result"]
    dep_id = dep["id"]
    print("deployment created:", dep_id, dep.get("url"))

    for _ in range(60):
        time.sleep(5)
        status, body = account_call(
            "GET",
            f"/accounts/{ACCOUNT_ID}/pages/projects/{PROJECT}/deployments/{dep_id}")
        payload = json.loads(body)
        stage = (payload.get("result") or {}).get("latest_stage") or {}
        print("stage:", stage.get("name"), stage.get("status"))
        if stage.get("status") == "success":
            print("DEPLOYMENT SUCCESS", dep.get("url"))
            return
        if stage.get("status") == "failure":
            print("DEPLOYMENT FAILED")
            sys.exit(1)
    print("deployment still running after polling window")
    sys.exit(2)


if __name__ == "__main__":
    main()
