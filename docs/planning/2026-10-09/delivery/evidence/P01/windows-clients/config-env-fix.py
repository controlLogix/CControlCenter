from pathlib import Path
root=Path('/home/ryan/.cache/agentmux-governance/windows-cli-links/20261009-192119');p=root/'forward.py';s=p.read_text();needle="if __name__=='__main__':"
insert='''def environment(original):
    result=dict(original)
    entries=[x for x in result.get('WSLENV','').split(':') if x]
    for key in ('CODEX_HOME','CLAUDE_CONFIG_DIR'):
        value=result.get(key)
        if not value:
            continue
        # Preserve other entries; an explicit config path must reach Windows.
        entries=[x for x in entries if x.split('/',1)[0] != key]
        windows_value=(len(value)>2 and value[1]==':' and value[2] in ('/',chr(92))) or value.startswith(chr(92)*2)
        entries.append(key+('/w' if windows_value else '/pw'))
    if entries:
        result['WSLENV']=':'.join(entries)
    return result

'''
assert needle in s;s=s.replace(needle,insert+needle).replace('os.execv(argv[0],argv)','os.execve(argv[0],argv,environment(os.environ))');p.write_text(s)