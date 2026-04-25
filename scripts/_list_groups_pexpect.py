#!/usr/bin/env python3
"""Pexpect wrapper that feeds OTP interactively."""
import pexpect, sys, os

CODE = sys.argv[1] if len(sys.argv) > 1 else None
PHONE = "+601173251590"

script = pexpect.spawn(
    "bash", ["-c",
        "cd /home/mssbai/Desktop/fraud-mvp && "
        "source venv/bin/activate && "
        "python3 _list_groups.py" + (f" {CODE}" if CODE else "")],
    encoding="utf-8",
    timeout=30,
    env={**os.environ, "TERM": "xterm-256color"},
)

while True:
    idx = script.expect([
        "Please enter your phone",
        "Please enter the code you received",
        "Enter code:",
        "DONE_AUTH",
        "TOTAL:",
        pexpect.EOF,
        pexpect.TIMEOUT,
    ])
    if idx == 0:
        script.sendline(PHONE)
    elif idx in (1, 2):
        if CODE:
            script.sendline(CODE)
        else:
            print("Need OTP but no code provided")
            break
    elif idx == 3:
        print("AUTH_SUCCESS", flush=True)
        break
    elif idx == 4:
        # TOTAL: output already printed
        break
    elif idx == 5:
        print("EOF:", script.before)
        break
    elif idx == 6:
        print("TIMEOUT. Buffer:", repr(script.buffer[-200:]))
        break

# Collect remaining output
try:
    script.expect(pexpect.EOF, timeout=10)
except pexpect.TIMEOUT:
    script.terminate()
print(script.before)
