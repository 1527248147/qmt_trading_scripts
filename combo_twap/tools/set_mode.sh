#!/usr/bin/env bash
#
# Hand the running strategy a new pricing instruction.
#
#   ./tools/set_mode.sh COMPETE              switch every name
#   ./tools/set_mode.sh QUEUE                switch back
#   ./tools/set_mode.sh COMPETE 600533.SH    switch one name only
#
# Why a NEW file rather than editing price_mode.txt: in LIVE mode the strategy
# could not open any file that existed before its session started -- observed
# six times on 2026-09-01, while every file it created itself opened fine. A
# file made DURING the session is not covered by that, so an instruction has to
# arrive as a new file. The strategy reads the HIGHEST-numbered one, because
# that is the most recent thing you said.
#
# This script finds the next free number and writes it. It never edits an
# existing file, so running it twice gives two instructions, not a conflict.

set -euo pipefail
cd "$(dirname "$0")/.."

MODE="${1:-}"
ONLY="${2:-}"

case "$MODE" in
    COMPETE|QUEUE) ;;
    *)
        echo "usage: $0 {COMPETE|QUEUE} [CODE.SH]" >&2
        echo "  COMPETE = counterparty price, fills now, pays the half-spread" >&2
        echo "  QUEUE   = rests at the touch, earns the spread, may not fill" >&2
        exit 1 ;;
esac

# Next free number. Gaps are fine -- only the highest matters -- but reusing a
# number would mean writing a file that already exists, which is the one thing
# the strategy cannot read.
n=1
while [ -e "price_mode${n}.txt" ]; do
    n=$((n + 1))
    if [ "$n" -gt 6 ]; then
        echo "price_mode1..6 are all taken. The strategy only looks at 1-6" >&2
        echo "(PRICE_MODE_MAX_SEQ), so delete the older ones or raise it." >&2
        exit 1
    fi
done

# CARRY THE CURRENT GLOBAL MODE FORWARD.
#
# The parser takes the bare word in a file as the default for every name, and
# a file WITHOUT one falls back to PRICE_MODE_DEFAULT. So writing a per-name
# line on its own silently resets the global mode: set COMPETE everywhere,
# then adjust one name, and the other nineteen quietly revert to QUEUE. Read
# the standing default out of the highest existing file and restate it.
GLOBAL="$MODE"
if [ -n "$ONLY" ]; then
    GLOBAL=""
    for f in $(ls -1 price_mode[1-9].txt price_mode.txt 2>/dev/null | sort -r); do
        w=$(grep -oE '^[[:space:]]*(COMPETE|QUEUE)[[:space:]]*$' "$f" 2>/dev/null | tr -d '[:space:]' | head -1)
        if [ -n "$w" ]; then GLOBAL="$w"; break; fi
    done
    [ -n "$GLOBAL" ] || GLOBAL="QUEUE"      # the script's own PRICE_MODE_DEFAULT
fi

F="price_mode${n}.txt"
{
    echo "# written $(date '+%Y-%m-%d %H:%M:%S') local by set_mode.sh"
    if [ -n "$ONLY" ]; then
        echo "# ${ONLY} -> ${MODE}; the line below restates the standing"
        echo "# default so the other names are not silently reset."
        echo "${GLOBAL}"
        echo "${ONLY}=${MODE}"
    else
        echo "${MODE}"
    fi
} > "$F"

echo "wrote $F:"
sed 's/^/    /' "$F"
echo
echo "The next bar should log:  price mode file -> ...\\${F}"
echo "If that line does not appear within two minutes, the file channel is"
echo "closed in this session and the mode can only be changed by re-pasting"
echo "the script with a different PRICE_MODE_DEFAULT."
