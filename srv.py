#!/usr/bin/env python3

import os
from http.server import HTTPServer, SimpleHTTPRequestHandler


class MyRequestHandler(SimpleHTTPRequestHandler):
    def send_acao(self):
        origin = self.headers["Origin"]
        self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Methods", "*")
        self.send_header("Access-Control-Allow-Credentials", "true")

    def send_content_type(self):
        content_type = ""
        if self.path.endswith(".m3u8"):
            content_type = "application/vnd.apple.mpegurl"
        elif self.path.endswith(".m4s"):
            content_type = "video/iso.segment"
        elif self.path.endswith(".mp4"):
            content_type = "video/mp4"

        if content_type != "":
            self.send_header("Content-type", content_type)

    def do_GET(self):
        data, ok = read_resource(os.path.basename(self.path))
        if not ok:
            self.send_response(404)
            self.end_headers()
            return

        self.send_response(200)
        self.send_acao()
        self.send_content_type()
        self.end_headers()
        self.wfile.write(data)
        return

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_acao()
        self.end_headers()
        return


def read_resource(basename):
    if os.path.exists("enc/"+basename):
        with open("enc/"+basename, "rb") as f:
            return f.read(), True
    if os.path.exists("keys/"+basename):
        with open("keys/"+basename, "rb") as f:
            return f.read(), True
    return b"", False


httpd = HTTPServer(("0.0.0.0", 8003), MyRequestHandler)
httpd.serve_forever()
