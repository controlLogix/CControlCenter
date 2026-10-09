import time,json,hashlib
from pathlib import Path
root=Path('/home/ryan/.cache/agentmux-governance/p01-dashboard-full-vkqiqkjv')
source=root/'tmp/tmp.0bjgx1ruOD/suite.log';dest=root/'evidence/dashboard-full-runner.log'
with source.open('rb') as src,dest.open('wb') as out:
 while True:
  block=src.read()
  if block:out.write(block);out.flush()
  for p in root.glob('tmp/agentmux-gate-fail-*.out'):
   (root/'evidence'/p.name).write_bytes(p.read_bytes())
  try:done='limits' in json.loads((root/'evidence/dashboard-full-result.json').read_text())
  except (OSError,ValueError):done=False
  if done:
   out.write(src.read());break
  time.sleep(.2)
print('runner log retained')
