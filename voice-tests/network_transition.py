#!/usr/bin/env python3
"""Inject a temporary loss transition into an owned, already recording profile."""
import argparse
import json
import os
from pathlib import Path
import shlex
import subprocess
import time
import uuid
import hashlib
from guest import read_guest
from network import GUEST, LEASE, PIPES
DRIVER_SOURCE = Path(__file__).read_text()


def profile_commands(profile, loss=None):
    settings = [(PIPES[0], profile['up_kbit']), (PIPES[1], profile['down_kbit'])]
    return [['/usr/sbin/dnctl', 'pipe', str(pipe), 'config', 'bw', f'{rate}Kbit/s',
                 'delay', f"{profile['delay_ms_each_way']}ms", 'plr', str(profile['configured_loss'] if loss is None else loss)]
                for pipe, rate in settings]


def restoration_program(owner_path, token, profile, marker, duration):
    commands = profile_commands(profile)
    return f'''import json,subprocess,time
from pathlib import Path
time.sleep({duration!r})
owner=Path({owner_path!r})
result={{"event":"network_loss_transition_restore","started_unix_ms":time.time_ns()/1e6}}
if owner.exists() and owner.read_text().strip()=={token!r}:
 for command in {commands!r}:subprocess.run(command,check=True)
 result["status"]="restored_prior_profile"
else:result["status"]="withheld_stale_owner"
result["completed_unix_ms"]=time.time_ns()/1e6
Path({marker!r}).write_text(json.dumps(result))
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('vm')
    parser.add_argument('network_directory', type=Path)
    parser.add_argument('capture_directory', type=Path)
    parser.add_argument('--at-s', type=float, required=True)
    parser.add_argument('--duration-s', type=float, default=45)
    parser.add_argument('--loss', type=float, default=.99)
    args = parser.parse_args()
    if not 0 <= args.at_s <= 1800 or not 15 <= args.duration_s <= 90 or not 0 <= args.loss < 1:
        raise ValueError('Require a bounded 15–90 second loss transition')
    state = json.loads((args.network_directory/'network-state.json').read_text())
    token = state['enable_token']
    if state['vm'] != args.vm or state.get('restored_at') or not token.isdecimal() or tuple(state['pipe_ids']) != PIPES:
        raise ValueError('Require this VM’s active owned profile')
    path = args.capture_directory/'host-events.jsonl'
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    ready = next(r['unix_ms']/1000 for r in rows if r['event']=='recorder_ready')
    if any(r['event']=='recording_complete' for r in rows) or not any(r['event']=='announcement_command_end' and r.get('outcome')=='accepted' for r in rows):
        raise ValueError('Require an active recording and an accepted playback probe')
    seconds = json.loads((args.capture_directory/'scenario.json').read_text())['seconds']
    if args.at_s + args.duration_s + 60 > seconds or time.time() >= ready + args.at_s:
        raise ValueError('Schedule a future transition with a recorded recovery interval')

    def record(event, **metadata):
        with path.open('a') as output:
            output.write(json.dumps(dict(source='host',event=event,unix_ms=time.time_ns()/1e6,
                                        transition_id=identifier,**metadata))+'\n')

    identifier = uuid.uuid4().hex
    (args.capture_directory/f'network-transition-driver-{identifier}.py').write_text(DRIVER_SOURCE)
    marker = f'/tmp/openbase-voice-transition-{identifier}.json'
    restore = restoration_program(LEASE, token, state['profile'], marker, args.duration_s)
    record('network_loss_transition_scheduled', at_s=args.at_s, duration_s=args.duration_s,
           driver_sha256=hashlib.sha256(DRIVER_SOURCE.encode()).hexdigest(),
           configured_loss=args.loss, classification='Deliberate fault injection; not steady-state coverage')
    while (remaining := ready + args.at_s - time.time()) > 0:
        time.sleep(min(20,remaining))
    program = f'''import json,subprocess,sys,time
from pathlib import Path
assert Path({LEASE!r}).read_text().strip()=={token!r},"Network owner changed"
timer=subprocess.Popen([sys.executable,"-c",{restore!r}],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
started=time.time_ns()/1e6
for command in {profile_commands(state['profile'],args.loss)!r}:subprocess.run(command,check=True,capture_output=True)
print(json.dumps({{"rollback_pid":timer.pid,"guest_started_unix_ms":started,"guest_completed_unix_ms":time.time_ns()/1e6}}))
'''
    result = subprocess.run([str(GUEST),'ssh',args.vm,'sudo -S -- python3 -c '+shlex.quote(program)],
        input=os.environ.get('VM_PASS','admin')+'\n',capture_output=True,text=True,timeout=30)
    record('network_loss_transition_apply', exit_code=result.returncode,
           receipt=json.loads(result.stdout) if result.returncode==0 else None,
           outcome='acknowledged' if result.returncode==0 else 'unconfirmed_no_retry')
    (args.capture_directory/'network-transition-stderr.txt').write_text(result.stderr)
    deadline = time.monotonic()+args.duration_s+30
    while time.monotonic() < deadline:
        observation = read_guest(GUEST,args.vm,'python3 -c '+shlex.quote(
            f'from pathlib import Path;p=Path({marker!r});print(p.read_text() if p.exists() else "")')).strip()
        if observation:
            evidence=json.loads(observation)
            (args.capture_directory/'network-transition-recovery.json').write_text(json.dumps(evidence,indent=2)+'\n')
            record('network_loss_transition_recovery_observed',guest=evidence)
            if evidence['status']!='restored_prior_profile':
                raise RuntimeError('Prior profile restoration withheld; inspect current owner')
            return
        time.sleep(2)
    raise RuntimeError('Guest transition restore unobserved; main profile safety timer remains armed')


if __name__=='__main__':
    main()
