#!/bin/bash

cat ../../data/andrew_ast/*.tsv > output.all.tsv
python computeAccuracy1.py output.all.tsv ../../data/rawTSV/dataset.staph.merged.txt --output output.all.comp.tsv > output.all.acc.txt
python statToTab.py output.all.acc.txt output.all.acc.tsv
python extractErrors.py output.all.comp.tsv output.all.err.tsv

for i in ../../data/andrew_ast/*.tsv; do
	echo $i
	python computeAccuracy1.py $i ../../data/rawTSV/dataset.staph.merged.txt --output accuracies/$(basename $i) > accuracies/$(basename $i | sed 's/.tsv/.stats.txt/g')
	python statToTab.py accuracies/$(basename $i | sed 's/.tsv/.stats.txt/g') accuracies/$(basename $i | sed 's/.tsv/.stats.tsv/g')
done