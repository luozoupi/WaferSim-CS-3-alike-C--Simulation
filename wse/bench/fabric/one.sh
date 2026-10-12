#!/bin/bash
# build + traced run of one case: one.sh <tag> [trace:1|0]
set -e; cd "$(dirname "$0")"; TAG=$1; TR=${2:-1}
D=runs/$TAG; mkdir -p $D
python3 gen.py $TAG > $D/layout.csl; cp pe.csl pe_ctl.csl run.py run_ctl.py $D/
RUN=run.py; grep -q pe_ctl.csl $D/layout.csl && RUN=run_ctl.py
W=$(grep "W, H =" $D/layout.csl | awk '{print $5}' | tr -d ,); H=$(grep "W, H =" $D/layout.csl | awk '{print $6}')
export PATH=/home/luo00466/cs_sdk:/home/luo00466/.local/opt/apptainer-1.5.3/bin:$PATH APPTAINERENV_SIMFAB_THREADS=2 APPTAINERENV_TRACE=$TR
cd $D; rm -rf out simfab_traces
flock /tmp/xkernel_singularity.lock cslc --arch=wse3 ./layout.csl --fabric-dims=$((W+7)),$((H+2)) --fabric-offsets=4,1 --params=W:$W,H:$H --memcpy --channels=1 -o out > compile.log 2>&1
flock /tmp/xkernel_singularity.lock cs_python $RUN --name out --json stamps.json > run.log 2>&1
grep -q SUCCESS run.log
if [ "$TR" = "1" ]; then python3 /home/luo00466/xkernel/studies/wse3-characterization/tools/decode_trace.py . -o events.jsonl.gz --quiet; rm -rf simfab_traces; fi
rm -rf out
echo "$TAG ok"
