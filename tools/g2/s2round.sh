#!/bin/bash
# G2 step 2 round: commit the Mesa tree, build on CI, run sweetca_test on the phone (j33 image).
#   bash tools/g2/s2round.sh NAME "commit message"
# Test output: logs/netlog-s2-NAME.txt.tests, kernel log: logs/netlog-s2-NAME.txt
cd "/c/Users/teleg/Documents/Code/Xiaomi A2/ios-jasmine" || exit 1
export MSYS_NO_PATHCONV=1
G="/c/Program Files/GitHub CLI/gh"
N=${1:?name}
wsl bash tools/g2/mkmesa.sh | tail -1
git add -A mesa tools && git -c user.name=telegdyd -c user.email=telegdyd93@gmail.com commit -q -m "${2:-libsweetca round $N}

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
git push -q origin jasmine
"$G" workflow run xnu.yml -R telegdyd/ios-jasmine --ref jasmine -f build=mesa
sleep 12
R=$("$G" run list -R telegdyd/ios-jasmine --workflow xnu.yml --limit 1 --json databaseId -q '.[0].databaseId')
echo "mesa run $R"
bash tools/g2/ci-wait.sh $R || exit 1
BINS="sweetca_test" PUSH="libsweetca.dylib" SECS=${SECS:-120} bash tools/g2/gpu-round.sh - $R j33 logs/netlog-s2-$N.txt 2>&1 | tail -3
grep -v "^  \|^ GPU\|^ CPU" logs/netlog-s2-$N.txt.tests | cut -c1-300
grep -n "SMMU fault\|SWEET PANIC\|panic(cpu" logs/netlog-s2-$N.txt | head
