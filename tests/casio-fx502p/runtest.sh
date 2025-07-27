#!/bin/sh

if [ $# -ne 1 ] ; then
	echo "usage: runtest.sh TEST" >&2
	exit 2
fi

rc=0
mkdir -p tmp

while true ; do
# Step 1: Decode the recorded .wav file into .cas and check that
# the output matches the expected result.
cmd="cstore fx502p save -i input/fx502p-$1.wav -o tmp/fx502p-$1.cas"
echo "run: $cmd"
eval $cmd
if [ $? -ne 0 ] ; then
	rc=1
	break
fi
diff tmp/fx502p-$1.cas expected/fx502p-$1.cas
if [ $? -ne 0 ] ; then
	echo "ERROR: output differs from expected result" >&2
	rc=1
	break
fi

# Step 2: Encode the .cas file into a temporary .wav, decode that again
# and check that the output still matches.
cmd="cstore fx502p load -i expected/fx502p-$1.cas -o tmp/fx502p-$1.wav"
echo "run: $cmd"
eval $cmd
if [ $? -ne 0 ] ; then
	rc=1
	break
fi
cmd="cstore fx502p save -i tmp/fx502p-$1.wav -o tmp/fx502p-$1.cas"
echo "run: $cmd"
eval $cmd
if [ $? -ne 0 ] ; then
	rc=1
	break
fi
diff tmp/fx502p-$1.cas expected/fx502p-$1.cas
if [ $? -ne 0 ] ; then
	echo "ERROR: output differs from expected result" >&2
	rc=1
	break
fi

break
done

if [ $rc -eq 0 ] ; then
	echo "PASS fx502p test $1"
	rm -r tmp
else
	echo "FAIL fx502p test $1" >&2
fi
echo ""
exit $rc
