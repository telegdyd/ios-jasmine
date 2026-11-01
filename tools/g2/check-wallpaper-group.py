#!/usr/bin/env python3
"""Compile the real sweetenv group matcher and check its process boundary."""
from pathlib import Path
import re
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
patch = (root / 'xnu/patches/j0121-jasmine-wallpaper-env-group.patch').read_text()
added = '\n'.join(line[1:] for line in patch.splitlines()
                  if line.startswith('+') and not line.startswith('+++'))
start = added.index('static int\nsweet_env_name_matches(')
helper = added[start:added.index('\n}', start) + 2]
expected = {
    'AegirPoster', 'CollectionsPoster', 'GradientPosterExtension',
    'PridePosterExtension', 'LegacyPoster', 'PhotosPosterProvider',
    'UnityPosterExtension', 'EmojiPosterExtension', 'ExtragalacticPoster',
}
members = set(re.findall(r'"([A-Za-z]+)"', helper))
injector = (root / 'mesa/metal/inject/bgmtl_sweet_inject.m').read_text()
section = injector.split('wallpaper_process(const char *name)', 1)[1].split('return NO;', 1)[0]
assert members == expected
# The injector withholds the device from members whose GPU work is known to hang (Pride, pool1 2026-11-01).
withheld = {'PridePosterExtension'}
assert set(re.findall(r'"([A-Za-z]+)"', section)) == expected - withheld

checks = []
for name in sorted(expected):
    # The selector is a bounded prefix of the actual boot entry, not a separate string.
    checks.append(f'if (!sweet_env_name_matches("@wallpaper:BGMTL_ENABLE=1", 10, "{name}")) return 1;')
for name in ['PosterBoard', 'xpcproxy', 'launchd', 'backboardd', 'SpringBoard', 'Preferences',
             'PosterBoardHelper', 'AegirPosterHelper', 'NotAegirPoster',
             'posterboard', 'Photos', '/Applications/PosterBoard.app/PosterBoard', '']:
    checks.append(f'if (sweet_env_name_matches("@wallpaper", 10, "{name}")) return 2;')
for selector in ['@wallpape', '@wallpaperX', 'wallpaper', '@Wallpaper']:
    checks.append(f'if (sweet_env_name_matches("{selector}", {len(selector)}, "AegirPoster")) return 3;')
checks += [
    'if (!sweet_env_name_matches("backboardd:BGMTL_ENABLE=1", 10, "backboardd")) return 4;',
    'if (sweet_env_name_matches("backboardd", 10, "backboarddHelper")) return 5;',
    'if (!sweet_env_name_matches("bgmtl_registered_probe", 22, "bgmtl_registered_probe")) return 6;',
]
# bgmtl_registered_probe has 22 characters including underscores.
assert len('bgmtl_registered_probe') == 22
source = '#include <stddef.h>\n#include <string.h>\n' + helper
source += '\nint main(void) {\n' + '\n'.join(checks) + '\nreturn 0;\n}\n'
with tempfile.TemporaryDirectory(prefix='wallpaper-group-') as temp:
    path = Path(temp)
    (path / 'check.c').write_text(source)
    subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror',
                    str(path / 'check.c'), '-o', str(path / 'check')], check=True)
    subprocess.run([str(path / 'check')], check=True)
print(f'PASS: {len(expected)} exact wallpaper members, {len(checks)} process-boundary checks; injector = kernel minus {sorted(withheld)}')
