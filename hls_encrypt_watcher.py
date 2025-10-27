#!/usr/bin/env python3
# encoding: utf-8

import argparse
import logging
import os
import re
import sys
import time
import shutil
import signal
from typing import Dict, Optional
from watchdog.observers import Observer
from watchdog.events import (
    FileSystemEventHandler,
)
from Crypto.Cipher import AES

BLOCKSIZE = 16
READ_CHUNK = 64 * 1024

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


# ===== Key / IV =====
def parse_key_info_file(path: str):
    with open(path, "r", encoding="utf-8") as f:
        lines = [l.strip() for l in f if l.strip()]
    if len(lines) < 2:
        raise ValueError("key_info file must have at least 2 lines: URI and local key path")
    key_uri, key_file = lines[:2]
    iv_bytes = parse_iv(lines[2]) if len(lines) >= 3 else None
    return key_uri, key_file, iv_bytes


def parse_iv(iv_str: str) -> bytes:
    s = iv_str.strip()
    if s.lower().startswith("0x"):
        s = s[2:]
    if len(s) != 32:
        raise ValueError(f"IV hex must be 16 bytes (32 hex chars), got {iv_str}")
    return bytes.fromhex(s)


def read_key_file(path: str) -> bytes:
    with open(path, "rb") as f:
        key = f.read()
    if len(key) != 16:
        logging.warning("Key file length is %d bytes (expected 16). Padding/truncating.", len(key))
    return key[:16].ljust(16, b"\x00")


# ===== AES =====
def pkcs7_pad_length(length: int) -> int:
    return BLOCKSIZE - (length % BLOCKSIZE)


def encrypt_file(in_path: str, out_path: str, key_bytes: bytes, iv_bytes: bytes):
    cipher = AES.new(key_bytes, AES.MODE_CBC, iv=iv_bytes)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(in_path, "rb") as fin, open(out_path, "wb") as fout:
        prev = b""
        while True:
            chunk = fin.read(READ_CHUNK)
            if not chunk:
                pad_len = pkcs7_pad_length(len(prev))
                padded = prev + bytes([pad_len]) * pad_len
                if padded:
                    fout.write(cipher.encrypt(padded))
                break
            data = prev + chunk
            full_len = (len(data) // BLOCKSIZE) * BLOCKSIZE
            if full_len > 0:
                fout.write(cipher.encrypt(data[:full_len]))
            prev = data[full_len:]


# ===== m3u8 =====
def build_ext_x_key(key_uri: str, iv_bytes: Optional[bytes]) -> str:
    line = f'#EXT-X-KEY:METHOD=AES-128,URI="{key_uri}"'
    if iv_bytes is not None:
        line += f",IV=0x{iv_bytes.hex()}"
    return line + "\n"


def insert_ext_x_key(lines, key_line: str):
    for i, l in enumerate(lines):
        if l.startswith("#EXT-X-KEY"):
            lines[i] = key_line
            break
    else:
        insert_at = None
        for i, l in enumerate(lines):
            if l.startswith("#EXT-X-MAP"):
                insert_at = i
                break
        if insert_at is None:
            for i, l in enumerate(lines):
                if l.startswith("#EXTINF") or not l.startswith("#"):
                    insert_at = i
                    break
        if insert_at is None:
            insert_at = len(lines)
        lines.insert(insert_at, key_line)
    return lines


class HLSHandler(FileSystemEventHandler):
    def __init__(
        self,
        key_uri: str,
        iv_bytes: Optional[bytes],
        key_bytes: bytes,
        src_dir: str,
        dst_dir: str,
        exts: set,
        pattern_re: Optional[re.Pattern],
        stable_tries: int,
        stable_interval: float,
    ):
        super().__init__()
        self.key_uri = key_uri
        self.iv_bytes = iv_bytes
        self.key_bytes = key_bytes
        self.src_dir = os.path.abspath(src_dir)
        self.dst_dir = os.path.abspath(dst_dir)
        self.exts = exts
        self.pattern_re = pattern_re
        self.stable_tries = stable_tries
        self.stable_interval = stable_interval
        self._processed_mtime: Dict[str, float] = {}

    # ---- utils ----
    def _rel_dst(self, src_path: str) -> str:
        rel = os.path.relpath(src_path, self.src_dir)
        return os.path.join(self.dst_dir, rel)

    def _process(self, path: str):
        if self._match_m3u8(path):
            self._process_m3u8(path)
        elif self._match_segment(path):
            self._process_segment(path)

    def _match_m3u8(self, path: str) -> bool:
        return path.lower().endswith(".m3u8")

    def _match_segment(self, path: str) -> bool:
        base = os.path.basename(path)
        if self.pattern_re:
            return bool(self.pattern_re.search(base))
        _, ext = os.path.splitext(base)
        return ext.lower() in self.exts

    def _stable_wait(self, src_path: str) -> bool:
        last_size = -1
        for _ in range(self.stable_tries):
            try:
                size = os.path.getsize(src_path)
            except FileNotFoundError:
                return False
            if size == last_size:
                return True
            last_size = size
            time.sleep(self.stable_interval)
        return False

    def _should_process(self, src_path: str) -> bool:
        try:
            mtime = os.path.getmtime(src_path)
        except FileNotFoundError:
            return False
        prev = self._processed_mtime.get(src_path)
        if prev is not None and mtime <= prev:
            return False
        self._processed_mtime[src_path] = mtime
        return True

    def _process_m3u8(self, src_path: str):
        if not os.path.exists(src_path):
            return
        if not self._should_process(src_path):
            return
        dst_path = self._rel_dst(src_path)
        os.makedirs(os.path.dirname(dst_path), exist_ok=True)
        try:
            with open(src_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            key_line = build_ext_x_key(self.key_uri, self.iv_bytes)
            lines = insert_ext_x_key(lines, key_line)
            with open(dst_path, "w", encoding="utf-8") as f:
                f.writelines(lines)
            logging.debug("m3u8 processed: %s -> %s", src_path, dst_path)
        except Exception:
            logging.exception("Failed to process m3u8: %s", src_path)

    def _process_segment(self, src_path: str):
        if not os.path.exists(src_path):
            return
        if not self._should_process(src_path):
            return
        stable = self._stable_wait(src_path)
        if not stable:
            logging.warning("Segment not stable; proceeding: %s", src_path)
        dst_path = self._rel_dst(src_path)
        try:
            encrypt_file(src_path, dst_path, self.key_bytes, self.iv_bytes or bytes(16))
            logging.debug("Encrypted: %s -> %s", src_path, dst_path)
        except Exception:
            logging.exception("Encrypt failed: %s", src_path)

    def _delete_mirror_path(self, src_path: str):
        dst_path = self._rel_dst(src_path)
        try:
            if os.path.exists(dst_path):
                os.remove(dst_path)
                self._processed_mtime.pop(src_path, None)
                logging.debug("Deleted mirror file: %s", dst_path)
        except Exception:
            logging.exception("Mirror delete failed: %s", dst_path)

    # ---- events ----
    def on_created(self, event):
        if event.is_directory:
            return
        self._process(event.src_path)

    def on_modified(self, event):
        if event.is_directory:
            return
        self._process(event.src_path)

    def on_moved(self, event):
        if event.is_directory:
            return
        self._process(event.dest_path)

    def on_deleted(self, event):
        if self._match_segment(event.src_path):
            self._delete_mirror_path(event.src_path)

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--key-info", help="Key info file (URI, local key, IV optional)")
    p.add_argument("--key-uri", help="Key URI")
    p.add_argument("--key-file", help="Local key file (16 bytes)")
    p.add_argument("--key-iv", dest="key_iv", help="IV (hex, 0x...)")
    p.add_argument("--src", required=True, help="Source directory (ffmpeg output root)")
    p.add_argument("--dst", required=True, help="Destination directory (encrypted mirror)")
    p.add_argument(
        "--exts",
        nargs="+",
        default=[".m4s", ".mp4", ".cmf"],
        help="Segment extensions to encrypt (ignored if --pattern is given)",
    )
    p.add_argument("--pattern", help="Regex for segment filenames (overrides --exts)")
    p.add_argument("--stable-tries", type=int, default=20, help="Tries to wait for file size to stabilize")
    p.add_argument("--stable-interval", type=float, default=0.1, help="Seconds between stability checks")
    args = p.parse_args()

    key_uri = key_file = iv_bytes = None
    if args.key_info:
        key_uri, key_file, iv_bytes = parse_key_info_file(args.key_info)
    if args.key_uri:
        key_uri = args.key_uri
    if args.key_file:
        key_file = args.key_file
    if args.key_iv:
        iv_bytes = parse_iv(args.key_iv)

    if not key_uri or not key_file:
        logging.error("Need key URI and key file (--key-info or --key-uri/--key-file)")
        sys.exit(2)

    key_bytes = read_key_file(key_file)
    exts = set(e if e.startswith(".") else "." + e for e in args.exts)
    pattern_re = re.compile(args.pattern) if args.pattern else None

    src = os.path.abspath(args.src)
    dst = os.path.abspath(args.dst)

    handler = HLSHandler(
        key_uri=key_uri,
        iv_bytes=iv_bytes,
        key_bytes=key_bytes,
        src_dir=src,
        dst_dir=dst,
        exts=exts,
        pattern_re=pattern_re,
        stable_tries=args.stable_tries,
        stable_interval=args.stable_interval,
    )
    for file_path in os.listdir(src):
        handler._process(src + "/" + file_path)

    observer = Observer()
    observer.schedule(handler, src, recursive=True)
    observer.start()

    logging.info("Watching src=%s -> dst=%s", src, dst)

    def _graceful_exit(signum, frame):
        logging.info("Stopping..., cleaning dst=%s", dst)
        shutil.rmtree(dst, ignore_errors=True)
        os.mkdir(dst)
        observer.stop()
    signal.signal(signal.SIGTERM, _graceful_exit)

    try:
        while observer.is_alive():
            time.sleep(1)
    except KeyboardInterrupt:
        _graceful_exit(None, None)
    observer.join()


if __name__ == "__main__":
    main()
