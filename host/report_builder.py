"""Build the clinical-report context (reports/templates/report.html) from
SandhiNaad session data + the bilingual questionnaire.

Everything in the report comes from what was actually measured or entered:
  - knee results  -> valid flex–extend cycles scored by the on-device model
  - questionnaire -> Patient & Questionnaire tab
  - data source   -> 'simulated' when the SIMULATOR port was used (adds watermark)
"""
from datetime import datetime

import numpy as np

from i18n import tr

OCC_KEYS = {'farmer': 'occupations.farmer', 'tea_garden_worker': 'occupations.teaGardenWorker',
            'homemaker': 'occupations.homemaker', 'laborer': 'occupations.laborer',
            'office_desk': 'occupations.officeDesk', 'student': 'occupations.student',
            'retired': 'occupations.retired', 'other': 'occupations.other'}
SQUAT_OCCUPATIONS = {'farmer', 'tea_garden_worker', 'laborer'}


def tier_of(p, n_valid):
    if n_valid < 1 or p is None:
        return 'indeterminate'
    if p < 0.3:
        return 'low'
    if p < 0.6:
        return 'moderate'
    return 'high'


def _yes(v):
    return v == 'yes'


def knee_block(k, t):
    """k: dict(side, probs[list], contribs[(name, contrib, z)], clicks, duration_s, crc_errors)."""
    probs = list(k.get('probs') or [])
    n = len(probs)
    p = float(np.median(probs)) if probs else None
    tier = tier_of(p, n)
    spread = (np.percentile(probs, 75) - np.percentile(probs, 25)) / 2 * 100 if n >= 2 else 0.0
    level = 'high' if n >= 5 and spread < 8 else ('moderate' if n >= 3 else 'low')
    conf = t['confidence_fmt'].replace('{level}', t['confidence_levels'][level]) \
        .replace('{n}', str(n)).replace('{spread}', f'{spread:.0f}')
    feats = []
    for name, contrib, z in sorted(k.get('contribs') or [], key=lambda c: -abs(c[1]))[:3]:
        ft = t['feature_text'].get(name) or t['feature_text']['_generic']
        feats.append({'name': name,
                      'plain_text': ft['up' if z >= 0 else 'down'].replace('{name}', name)})
    link_bad = k.get('crc_errors', 0) > 0
    lowq = k.get('low_quality', 0)
    if lowq and n and lowq * 2 >= n:
        level = 'low'
        conf = t['confidence_fmt'].replace('{level}', t['confidence_levels'][level]) \
            .replace('{n}', str(n)).replace('{spread}', f'{spread:.0f}')
    qc_ok = n >= 3 and not link_bad and lowq * 2 < n
    reason = t['qc_reasons']['ok' if qc_ok else ('link_errors' if link_bad else
                                                 ('few_cycles' if n < 3 else 'low_quality'))]
    return {'side': k.get('side', 'right'), 'tier': tier, 'probability': p, 'confidence': conf,
            'top_features': feats,
            'qc': {'passed': qc_ok, 'valid_events': int(k.get('clicks', 0)), 'reps': n,
                   'contact_quality': '', 'reason': reason},
            'session': {'duration_s': int(round(k.get('duration_s', 0))), 'reps': n,
                        'exercise': t['exercise_protocol']}}


def build_context(state, knees, device, lang, t, clinical_prior=None, model_info=None):
    """state: QuestionnairePanel.get_state(); knees: list of knee dicts; t: report i18n."""
    pt, wk, q, ex = state['patient'], state['worker'], state['q'], state['exam']
    L = lambda key: tr(key, lang)  # noqa: E731
    sex = {'male': L('patient.male'), 'female': L('patient.female'), 'other': L('patient.other')}.get(pt['sex'], '')
    now = datetime.now()

    pain_act = max(q.get('pain_activity_left', 0), q.get('pain_activity_right', 0))
    kblocks = [knee_block(k, t) for k in knees]
    order = ['indeterminate', 'low', 'moderate', 'high']
    worst = max((b['tier'] for b in kblocks), key=order.index) if kblocks else 'indeterminate'
    red = [k for k, v in q.get('red_flags', {}).items() if v]

    def dur():
        if not q.get('duration_value'):
            return ''
        return f"{q['duration_value']} {t['durations'].get(q.get('duration_unit', 'months'), '')}"

    affected = {'left': t['sides']['left'], 'right': t['sides']['right'],
                'both': f"{t['sides']['right']} + {t['sides']['left']}"}.get(q.get('affected_knee'), '')
    pr = []
    for side in ('right', 'left'):
        pr.append(f"{t['sides'][side]}: {q.get('pain_rest_' + side, 0)}/{q.get('pain_activity_' + side, 0)}")

    mi = model_info or {}
    return {
        'patient': {'id': pt['id'], 'name': pt['name'], 'age': pt['age'], 'sex': sex,
                    'height_cm': pt['height_cm'], 'weight_kg': pt['weight_kg'], 'bmi': pt['bmi'],
                    'occupation': L(OCC_KEYS.get(pt['occupation'], 'occupations.other')),
                    'district': pt['district'] or '—', 'block': pt['block'] or '—'},
        'screening': {'id': f"SCR-{now:%Y%m%d-%H%M}", 'date': f"{now:%Y-%m-%d %H:%M}",
                      'worker_name': wk['name'] or '—', 'worker_role': wk['role'] or '—',
                      'facility': wk['facility'] or '—', 'worker_id': wk['id'] or '—',
                      'device_id': device.get('device_id', 'ESP32'), 'app_version': device.get('fw', ''),
                      'data_source': device.get('data_source', 'hardware'), 'language': lang},
        'questionnaire': {'pain_score': pain_act,
                          'morning_stiffness_minutes': q.get('morning_stiffness_min', 0),
                          'difficulty_stairs': _yes(q.get('stairs')), 'difficulty_squat': _yes(q.get('squatting')),
                          'difficulty_kneel': _yes(q.get('kneeling')), 'difficulty_chair': _yes(q.get('standing_chair')),
                          'night_pain': _yes(q.get('night_pain')), 'swelling': _yes(q.get('swelling')),
                          'prior_injury': _yes(q.get('injury_left')) or _yes(q.get('injury_right')),
                          'family_history': _yes(q.get('family_history'))},
        'history': {'affected_knee': affected, 'symptom_duration': dur(), 'pain_rest_activity': ' | '.join(pr),
                    'comorbidities': [c for c in ('diabetes', 'inflammatory_arthritis', 'gout') if _yes(q.get(c))],
                    'pain_medicine': _yes(q.get('pain_medicine')), 'walking_aid': _yes(q.get('walking_aid'))},
        'red_flags': red,
        'clinical_check': {'effusion': ex.get('effusion'), 'tenderness': ex.get('tenderness'),
                           'bony_enlargement': ex.get('bony_enlargement'), 'warmth': ex.get('warmth'),
                           'crepitus': ex.get('crepitus'), 'flexion_deg': ex.get('flexion_deg') or None,
                           'alignment': ex.get('alignment'), 'gait_note': ex.get('gait_note', '')},
        'knees': kblocks,
        'advice': {'tier': worst, 'items': [], 'reviewed': False},
        'referral': {'key': 'priority_chc' if red else None, 'recommended_action': ''},
        'clinical_prior': clinical_prior,
        'model': {'name': mi.get('name', 'SandhiNaad acoustic–kinematic LR'),
                  'version': mi.get('version', ''), 'synthetic': mi.get('synthetic', True)},
    }


def prior_inputs(state):
    """Map questionnaire answers to the clinical prior model inputs (ml/config.py).

    koos_pain / koos_function are not asked directly; they are approximated from the
    NRS pain scores and the functional-difficulty answers (documented in the UI)."""
    pt, q = state['patient'], state['q']
    if not pt.get('age'):
        return {}
    pain = max(q.get('pain_activity_left', 0), q.get('pain_activity_right', 0),
               q.get('pain_rest_left', 0), q.get('pain_rest_right', 0))
    func_keys = ['pain_movement', 'stairs', 'squatting', 'kneeling', 'standing_chair',
                 'swelling', 'locking', 'giving_way', 'night_pain']
    answered = [q.get(k) for k in func_keys if q.get(k) in ('yes', 'no')]
    frac = (sum(a == 'yes' for a in answered) / len(answered)) if answered else 0.0
    return {'age': float(pt['age']), 'sex': 1.0 if pt['sex'] == 'female' else 0.0,
            'bmi': float(pt['bmi'] or 0),
            'occupation_squat': 1.0 if (pt['occupation'] in SQUAT_OCCUPATIONS
                                        or pt.get('kneel_hours', 0) >= 2) else 0.0,
            'koos_pain': float(100 - 10 * pain), 'koos_function': float(100 - 100 * frac)}
