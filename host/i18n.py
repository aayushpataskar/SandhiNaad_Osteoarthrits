"""Tiny translation helper for the desktop UI.

Strings live in host/i18n/<lang>.json (same files/keys as the OA-NER web app,
plus an 'sn' section for SandhiNaad-specific UI). tr('complaint.stairs', 'as').
Missing keys fall back to English, then to the key itself.
"""
import json
import os

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'i18n')
_cache = {}
LANGS = {
    'en': 'English',
    'as': 'অসমীয়া (Assamese)',
    'bn': 'বাংলা (Bengali)',
    'brx': 'बड़ो (Bodo)',
    'mni': 'মৈতৈলোন্ (Manipuri)',
    'lus': 'Mizo',
    'kha': 'Khasi',
    'grt': 'Garo (A·chik)',
    'trp': 'ককবরক (Kokborok)',
    'nag': 'Nagamese',
    'ne': 'नेपाली (Nepali)',
}


def _load(lang):
    if lang not in _cache:
        try:
            with open(os.path.join(_DIR, f'{lang}.json'), encoding='utf-8') as f:
                _cache[lang] = json.load(f)
        except OSError:
            _cache[lang] = {}
    return _cache[lang]


def _get(d, key):
    for part in key.split('.'):
        if not isinstance(d, dict) or part not in d:
            return None
        d = d[part]
    return d if isinstance(d, str) else None


def tr(key, lang='en', **fmt):
    s = _get(_load(lang), key) or _get(_load('en'), key) or key
    for k, v in fmt.items():
        s = s.replace('{' + k + '}', str(v)).replace('{{' + k + '}}', str(v))
    return s
