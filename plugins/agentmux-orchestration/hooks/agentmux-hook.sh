#!/bin/sh
nl=$(printf '\nx'); nl=${nl%x}; payload=; while IFS= read -r line || [ -n "$line" ]; do payload="$payload$line$nl"; [ "${#payload}" -le 262144 ] || { printf '%s\n' 'agentmux hook: input exceeds the size limit' >&2; exit 2; }; done
case "${1-}:$payload" in pre-bash:*hire*|pre-bash:*agent*|pre-bash:*coordination*|pre-bash:*runtime.py*|pre-bash:*rm*|pre-bash:*mv*|pre-bash:*cp*|pre-bash:*sed*|pre-bash:*tee*|pre-bash:*python*|pre-bash:*perl*|pre-bash:*curl*|pre-bash:*wget*|pre-bash:*http*|pre-bash:*install*|pre-bash:*truncate*|pre-bash:*touch*|pre-bash:*chmod*|pre-bash:*chown*|pre-bash:*\>*|pre-bash:*\\*) ;; pre-bash:*) exit 0 ;; esac
# Recognize only an ordinary pwd event without starting another process. Parse
# every field so metadata cannot hide duplicate keys or a second command. Other
# commands, escapes, large frames and unknown host fields use the full parser.
plain_pwd_event() {
  [ "${#payload}" -le 8192 ] || return 1
  case "$payload" in *\\*) return 1 ;; esac
  rest=$payload; state=start; seen='|'; command_seen=; cr=$(printf '\r'); tab=$(printf '\t')
  while [ -n "$rest" ]; do
    ch=${rest%"${rest#?}"}; rest=${rest#?}
    case "$ch" in ' '|"$tab"|"$nl"|"$cr") continue ;; esac
    token=$ch
    if [ "$ch" = '"' ]; then
      token=; closed=
      while [ -n "$rest" ]; do
        ch=${rest%"${rest#?}"}; rest=${rest#?}
        [ "$ch" != '"' ] || { closed=1; break; }
        case "$ch" in "$nl"|"$cr"|"$tab") return 1 ;; esac
        token=$token$ch
      done
      [ "$closed" = 1 ] || return 1
      kind=string
    else
      kind=punctuation
    fi
    case "$state:$kind:$token" in
      start:punctuation:\{) state=key ;;
      key:string:*)
        case "$seen" in *"|$token|"*) return 1 ;; esac
        seen=$seen$token'|'
        case "$token" in
          tool_input) state=input_colon ;;
          cwd|transcript_path|session_id|tool_name|permission_mode|hook_event_name|tool_use_id) state=metadata_colon ;;
          *) return 1 ;;
        esac ;;
      metadata_colon:punctuation::) state=metadata_value ;;
      metadata_value:string:*) state=outer_end ;;
      input_colon:punctuation::) state=input_open ;;
      input_open:punctuation:\{) state=command_key ;;
      command_key:string:command) state=command_colon ;;
      command_colon:punctuation::) state=command_value ;;
      command_value:string:pwd) command_seen=1; state=input_end ;;
      input_end:punctuation:\}) state=outer_end ;;
      outer_end:punctuation:,) state=key ;;
      outer_end:punctuation:\}) state=done ;;
      *) return 1 ;;
    esac
  done
  [ "$state:$command_seen" = done:1 ]
}
if [ "${1-}" = pre-bash ] && plain_pwd_event; then exit 0; fi
root=${0%/*}/..
printf '%s' "$payload" | python3 "$root/bin/agentmux-plugin" "$@"
