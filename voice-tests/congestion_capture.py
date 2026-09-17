#!/usr/bin/env python3
"""Checked guest shaping, measurement and acoustic capture under one lease."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
from acoustic_session import acoustic_session
import capture

ROOT=Path(__file__).resolve().parents[1]


def step(arguments, evidence):
    with (evidence/'orchestration.log').open('a') as log:
        subprocess.run([sys.executable,*arguments],stdout=log,stderr=subprocess.STDOUT,check=True)


def network_preflight(vm, evidence, profile, *, measurement_bytes=25000):
    step([str(ROOT/'voice-tests/network.py'),'apply',vm,str(evidence),*profile],evidence)
    state=json.loads((evidence/'network-state.json').read_text())
    if state.get('vm')!=vm or state.get('restored_at'):
        raise ValueError('Confirmed current shaping ownership is required')
    step([str(ROOT/'voice-tests/measure_network.py'),vm,str(evidence),
        '--download-bytes',str(measurement_bytes),'--upload-bytes',str(measurement_bytes)],evidence)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('vm');parser.add_argument('scenario',type=Path)
    parser.add_argument('output',type=Path);parser.add_argument('network_directory',type=Path)
    parser.add_argument('--manifest',type=Path,required=True)
    parser.add_argument('--credentials-file',type=Path,required=True)
    parser.add_argument('--reuse-stimuli',type=Path)
    parser.add_argument('--down-kbit',type=int,default=128)
    parser.add_argument('--up-kbit',type=int,default=768)
    parser.add_argument('--delay-ms',type=int,default=200)
    parser.add_argument('--loss',type=float,default=.02)
    parser.add_argument('--after-recorder-s',type=float,default=230)
    parser.add_argument('--safety-seconds',type=int,default=900)
    parser.add_argument('--measurement-bytes',type=int,default=25000)
    args=parser.parse_args()
    if args.vm not in json.loads(args.manifest.read_text())['clones']:
        raise ValueError('A declared disposable run clone is required')
    scenario=json.loads(args.scenario.read_text())
    if scenario.get('stimuli') and not args.reuse_stimuli:
        raise ValueError('Prepare stimuli before congestion capture; provide --reuse-stimuli')
    if args.output.exists():
        raise ValueError('Capture output must be a new directory')
    if not 0<args.after_recorder_s<float(scenario['seconds']):
        raise ValueError('Recovery must occur within the planned recording')
    with acoustic_session(ROOT/'.local/field-tests/acoustic-session.lock'):
        args.network_directory.mkdir(parents=True,exist_ok=False)
        state=args.network_directory/'network-state.json'
        recovery=None
        started=time.time_ns()/1e6
        try:
            network_preflight(args.vm,args.network_directory,[
                '--down-kbit',str(args.down_kbit),'--up-kbit',str(args.up_kbit),
                '--delay-ms',str(args.delay_ms),'--loss',str(args.loss),
                '--safety-seconds',str(args.safety_seconds)],measurement_bytes=args.measurement_bytes)
            with (args.network_directory/'scheduled-recovery.log').open('w') as log:
                recovery=subprocess.Popen([sys.executable,str(ROOT/'voice-tests/network_recovery.py'),
                    args.vm,str(args.network_directory),str(args.output),
                    '--after-recorder-s',str(args.after_recorder_s)],stdout=log,stderr=subprocess.STDOUT)
                arguments=[str(args.scenario),str(args.output),'--credentials-file',
                    str(args.credentials_file),'--vm',args.vm]
                if args.reuse_stimuli:
                    arguments+=['--reuse-stimuli',str(args.reuse_stimuli)]
                capture.main(arguments)
                if recovery.wait(timeout=30):
                    raise RuntimeError('Scheduled restoration failed; preserve recovery evidence')
        finally:
            if recovery is not None and recovery.poll() is None:
                recovery.terminate();recovery.wait(timeout=10)
            # State exists only if this new evidence directory acquired ownership.
            # The guest rollback remains armed if a restore acknowledgment is lost.
            if state.exists():
                step([str(ROOT/'voice-tests/network.py'),'restore',args.vm,str(args.network_directory)],args.network_directory)
            (args.network_directory/'orchestration.json').write_text(json.dumps({
                'host_started_unix_ms':started,'host_finished_unix_ms':time.time_ns()/1e6,
                'shaping_state_created':state.exists(),
                'capture_created':args.output.exists(),
                'limitation':'Phone readiness, speaker verification, stimulus permits and finish guard remain separate Appium gates.'},indent=2)+'\n')


if __name__=='__main__':
    main()
