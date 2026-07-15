#!/usr/bin/env python3
# Simulates the SET_BRIGHTNESS command parser to demonstrate the bug fix.
# Mirrors the Arduino String semantics: toInt() returns 0 for non-numeric,
# and only consumes a leading numeric run.

MAX_LED_BRIGHTNESS = 80


def to_int(s: str) -> int:
    """Replicate Arduino String::toInt(): parse optional leading '-' + digits,
    stop at first non-digit, return 0 if nothing parsed."""
    s = s.strip()
    if not s:
        return 0
    i = 0
    negative = False
    if s[0] == '-':
        negative = True
        i = 1
    elif s[0] == '+':
        i = 1
    start = i
    while i < len(s) and s[i].isdigit():
        i += 1
    if i == start:
        return 0
    val = int(s[start:i])
    return -val if negative else val


def is_decimal_number(s: str) -> bool:
    s = s.strip()
    if not s:
        return False
    return all('0' <= c <= '9' for c in s)


def old_parser(arg: str):
    arg = arg.strip()
    val = to_int(arg)
    if arg == "" or val < 0 or val > 255:
        return "ERR BAD_ARG"
    return f"OK SET_BRIGHTNESS {val}"


def new_parser(arg: str):
    arg = arg.strip()
    if not is_decimal_number(arg):
        return "ERR BAD_ARG"
    val = to_int(arg)
    if val < 0 or val > 255:
        return "ERR BAD_ARG"
    return f"OK SET_BRIGHTNESS {val}"


CASES = ["abc", "40", "200", "255", "256", "300", "", "12abc", "abc12",
         "-5", "0", " 40 ", "0xFF"]

print(f"{'arg':<8} | {'OLD (buggy)':<20} | {'NEW (fixed)':<20}")
print("-" * 52)
for c in CASES:
    print(f"{c!r:<8} | {old_parser(c):<20} | {new_parser(c):<20}")
