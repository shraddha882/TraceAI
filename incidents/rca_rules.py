"""Explicit cross-source leads, not causal conclusions or probability scores."""
import re

RULES = (
    ('DB_CONNECTION_USAGE', 'Database connection pressure may be contributing',
     r'\b(?:too many connections|remaining connection slots|connection pool exhausted|connection pool timeout)\b',
     'Inspect pool occupancy, connection lifecycle and database client origins; compare with the pre-incident baseline.'),
    ('DB_LOCK_WAIT', 'Database lock contention may be contributing',
     r'\b(?:deadlock detected|lock wait timeout|lock timeout|canceling statement due to lock timeout)\b',
     'Inspect blocking and blocked transactions and their start times. Confirm affected queries before considering transaction changes.'),
    ('DB_SLOW_QUERY', 'Database query latency may be contributing',
     r'\b(?:statement timeout|query timed out|query timeout|slow query)\b',
     'Match the logged query to the captured query sample, inspect its plan and compare normal latency before changing indexes or timeouts.'),
)


def database_hypotheses(events):
    hypotheses = []
    for rule, title, pattern, checks in RULES:
        databases = [row for row in events if row['kind'] == 'database' and any(f.get('rule') == rule for f in row.get('findings', []))]
        logs = [row for row in events if row['kind'] == 'log' and re.search(pattern, row['title'], re.I)]
        # Require nearby corroboration as well as the incident's overall window.
        pairs = [(db, log) for db in databases for log in logs if abs((db['time'] - log['time']).total_seconds()) <= 300]
        if not pairs:
            continue
        db, log = min(pairs, key=lambda pair: (abs((pair[0]['time'] - pair[1]['time']).total_seconds()), pair[0]['identity'], pair[1]['identity']))
        evidence = [db, log]
        traces = [row for row in events if row['kind'] == 'trace' and row['signal'] and row['service_match'] == 'match'
                  and abs((row['time'] - db['time']).total_seconds()) <= 300
                  and abs((row['time'] - log['time']).total_seconds()) <= 300]
        if traces:
            evidence.append(traces[0])
        matched = [f for f in db['findings'] if f.get('rule') == rule]
        hypotheses.append({
            'rule': rule, 'title': title, 'confidence': 'Low — service/database ownership unverified',
            'reason': f'{rule} metric finding and a matching error-log phrase occur within five minutes. '
                      + ('A same-service error/slow trace is nearby; it is a symptom, not proof of a database call.' if traces else 'No qualifying same-service trace supports this lead.'),
            'evidence': evidence, 'matched_findings': matched,
            'limitations': 'Log service identity, database-to-service mapping and environment are unverified. Phrase matching can include quoted or negated errors. '
                           'A trace dependency, matching query/client identity and a pre-incident baseline are missing. These sources may describe unrelated activity. '
                           'Only the closest log/metric pair per rule is shown; repeated messages do not increase confidence.',
            'checks': checks,
        })
    return hypotheses
