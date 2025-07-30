#!/bin/sh

function run_one_calc() {
	(
		cd $1
		./runall.sh
	)
}

run_one_calc tests/casio-fx502p || exit 1
run_one_calc tests/sharp-pc1211 || exit 1
run_one_calc tests/sharp-pc1211-res || exit 1
