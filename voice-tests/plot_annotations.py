"""Only acknowledged fault intervals become plotted network-loss bands."""


def loss_intervals(rows, duration):
    starts = [r for r in rows if r['event']=='network_loss_transition_guest_apply_completed']
    stops = [r for r in rows if r['event']=='network_loss_transition_guest_restore_started'
             and r.get('metadata',{}).get('status')=='restored_prior_profile']
    result = []
    for start in starts:
        identity=start.get('metadata',{}).get('transition_id')
        matching=[r['capture_relative_s'] for r in stops
                  if r['capture_relative_s'] >= start['capture_relative_s']
                  and r.get('metadata',{}).get('transition_id')==identity]
        result.append((start['capture_relative_s'],min(matching) if matching else duration,
                       'Injected network loss' if matching else 'Injected loss; restore unobserved'))
    return result
