#!/bin/sh

if [ $# -ne 1 ] ; then
	echo "usage: runtest.sh TEST" >&2
	exit 2
fi

rc=0
mkdir -p tmp

while true ; do
# Step 1: Decode the recorded .wav file into .bas and check that
# the output matches the expected result.
cmd="cstore pc1211 save -i input/pc1211-$1.wav -o tmp/pc1211-$1.bas"
echo "run: $cmd"
eval $cmd
if [ $? -ne 0 ] ; then
	rc=1
	break
fi
diff tmp/pc1211-$1.bas expected/pc1211-$1.bas
if [ $? -ne 0 ] ; then
	echo "ERROR: output differs from expected result" >&2
	rc=1
	break
fi

# Step 2: Encode the .bas file into a temporary .wav, decode that again
# and check that the output still matches.
cmd="cstore pc1211 load -i expected/pc1211-$1.bas -o tmp/pc1211-$1.wav"
echo "run: $cmd"
eval $cmd
if [ $? -ne 0 ] ; then
	rc=1
	break
fi
cmd="cstore pc1211 save -i tmp/pc1211-$1.wav -o tmp/pc1211-$1.bas"
echo "run: $cmd"
eval $cmd
if [ $? -ne 0 ] ; then
	rc=1
	break
fi
diff tmp/pc1211-$1.bas expected/pc1211-$1.bas
if [ $? -ne 0 ] ; then
	echo "ERROR: output differs from expected result" >&2
	rc=1
	break
fi

break
done

if [ $rc -eq 0 ] ; then
	echo "PASS pc1211 test $1"
	rm -r tmp
else
	echo "FAIL pc1211 test $1" >&2
fi
echo ""
exit $rc
