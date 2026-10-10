import sys,os,pathlib
ROOT=pathlib.Path(os.environ['HAR20_ROOT']).resolve()
def audit(event,args):
 if event in ('socket.connect','socket.bind','subprocess.Popen','os.system'):raise AssertionError('External action forbidden: '+event)
 if event=='open' and isinstance(args[0],(str,bytes,os.PathLike)):
  flags=args[2] or 0
  if flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND):
   assert pathlib.Path(os.fsdecode(args[0])).resolve().is_relative_to(ROOT), args[0]
sys.addaudithook(audit)
