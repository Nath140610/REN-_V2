"""Mise en page des réponses de NathGPT.

NathGPT reçoit un pré-prompt qui l'oblige à répondre avec des balises courtes, une par ligne :
    [TITRE] Ton code cadeau
    [TEXTE] Ton code n'est pas encore activé.
    [ENCART] Valable jusqu'au : jeudi 18 h
    [ETAPES] Ouvre ta carte | Gratte-la | Entre le code dans ChristmasRun
René lit ces balises et construit un embed Discord (ou des blocs pour le panel) au lieu d'un gros pavé.
Une réponse sans balise reste lisible : elle est découpée en paragraphes.
"""
from __future__ import annotations

import re
import unicodedata

import discord

TAGS = {
    'TITRE': 'title', 'TITLE': 'title',
    'TEXTE': 'text', 'TEXT': 'text', 'PARAGRAPHE': 'text',
    'ENCART': 'box', 'ENCARD': 'box', 'ENCADRE': 'box', 'ENCADREE': 'box', 'INFO': 'box',
    'CHIFFRE': 'stat', 'CHIFFRES': 'stat', 'STAT': 'stat',
    'LISTE': 'list', 'LIST': 'list', 'POINTS': 'list',
    'ETAPES': 'steps', 'ETAPE': 'steps',
    'ASTUCE': 'tip', 'CONSEIL': 'tip',
    'ATTENTION': 'warning', 'IMPORTANT': 'warning',
    'QUESTION': 'question',
    'COULEUR': 'color',
}
COLORS = {'bleu': 0x0A84FF, 'vert': 0x30D158, 'orange': 0xFF9F0A, 'rouge': 0xFF453A,
          'violet': 0x965AFF, 'rose': 0xFF46AA, 'jaune': 0xFFD60A}
DEFAULT_COLOR = 0x965AFF
TAG_LINE = re.compile(r'^\s*[*_]*\[\s*([A-Za-zÀ-ÿ]+)\s*\][*_]*\s*:?\s*(.*)$')

FORMAT_RULES = (
    'FORMAT OBLIGATOIRE. Réponds uniquement avec ces balises, chacune au début d’une ligne :\n'
    '[TITRE] titre court (6 mots maximum, une seule fois, en premier)\n'
    '[TEXTE] une ou deux phrases courtes\n'
    '[ENCART] Libellé : valeur  (une info importante mise en avant, ex. [ENCART] Le jeudi : 18 h)\n'
    '[CHIFFRE] Libellé : valeur  (un chiffre clé, ex. [CHIFFRE] Messages : 1 240)\n'
    '[LISTE] élément | élément | élément\n'
    '[ETAPES] étape | étape | étape\n'
    '[ASTUCE] un conseil pratique\n'
    '[ATTENTION] un avertissement\n'
    '[QUESTION] une question à poser à la personne\n'
    '[COULEUR] bleu, vert, orange, rouge, violet ou rose (facultatif, selon le ton)\n'
    'Règles : pas de Markdown (#, **, tableaux), pas de phrase hors balise, pas de bloc de plus de deux phrases, '
    'sépare les éléments de [LISTE] et [ETAPES] par « | », laisse une ligne vide entre deux balises. '
    'Utilise seulement les balises utiles. '
    'Exemple :\n[TITRE] Code bientôt actif\n[TEXTE] Ta carte doit d’abord être grattée.\n'
    '[ENCART] Validité : 24 h après le grattage\n[ETAPES] Ouvre le lien reçu en MP | Gratte la carte | '
    'Entre le code dans le jeu\n[QUESTION] Tu as bien reçu le MP de René ?\n'
)


def pre_prompt(max_chars: int = 900) -> str:
    return (FORMAT_RULES + f'Longueur totale : {max_chars} caractères maximum. Réponds en français.\n')


def tag_name(raw: str) -> str:
    raw = unicodedata.normalize('NFKD', raw.upper())
    return ''.join(c for c in raw if c.isalpha() and not unicodedata.combining(c))


def strip_markdown(text: str) -> str:
    text = re.sub(r'^\s*#{1,6}\s*', '', text)
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    return text.strip().strip('*_ ').strip()


def split_label(text: str) -> tuple[str, str]:
    text = text.strip()
    if text.startswith('(') and text.endswith(')'):
        text = text[1:-1].strip()
    if ':' in text:
        label, value = text.split(':', 1)
        if label.strip() and value.strip() and len(label) <= 80:
            return label.strip(), value.strip()
    return '', text


def split_items(text: str) -> list[str]:
    parts = re.split(r'\s*\|\s*|\n+', text)
    return [re.sub(r'^\s*(?:[-•*]|\d+[.)])\s*', '', p).strip() for p in parts if p.strip()][:15]


INLINE_TAG = re.compile(r'[*_]*\\?\[\s*([A-Za-zÀ-ÿ]{3,12})\s*\\?\][*_]*')


def one_tag_per_line(answer: str) -> str:
    """ChatGPT affiche du Markdown : un simple retour à la ligne y devient un espace, donc NathGPT renvoie
    parfois toutes les balises sur une seule ligne (« [TITRE] Bilan [TEXTE] … ») ou échappées (« \\[TITRE\\] »).
    Chaque balise connue est remise au début d'une ligne."""
    def cut(match: re.Match) -> str:
        if tag_name(match.group(1)) not in TAGS:
            return match.group(0)
        return f'\n[{match.group(1)}] '
    return INLINE_TAG.sub(cut, str(answer or '').replace('\r', ''))


def parse(answer: str) -> list[dict]:
    """Découpe la réponse en blocs : title, text, box, stat, list, steps, tip, warning, question, color."""
    blocks: list[dict] = []
    current: dict | None = None
    for line in one_tag_per_line(answer).split('\n'):
        match = TAG_LINE.match(line)
        kind = TAGS.get(tag_name(match.group(1))) if match else None
        if kind:
            current = {'type': kind, 'raw': match.group(2).strip()}
            blocks.append(current)
        elif line.strip():
            if current is None or current['type'] in ('title', 'color'):
                current = {'type': 'text', 'raw': line.strip()}
                blocks.append(current)
            else:
                current['raw'] += '\n' + line.strip()
        elif current is not None and current['type'] == 'text':
            current = None   # ligne vide : nouveau paragraphe
    result = []
    for block in blocks:
        raw = strip_markdown(block['raw'])
        kind = block['type']
        if not raw:
            continue
        if kind in ('box', 'stat'):
            label, value = split_label(raw)
            result.append({'type': kind, 'label': label[:80], 'text': value[:900]})
        elif kind in ('list', 'steps'):
            items = [i[:300] for i in split_items(raw)]
            if items:
                result.append({'type': kind, 'items': items})
        elif kind == 'color':
            result.append({'type': 'color', 'text': raw.split()[0].lower()})
        else:
            result.append({'type': kind, 'text': raw[:1500]})
    return result


def plain(blocks: list[dict]) -> str:
    """Version texte (messages simples, journaux)."""
    lines = []
    for b in blocks:
        kind = b['type']
        if kind == 'title':
            lines.append(f'**{b["text"]}**')
        elif kind in ('box', 'stat'):
            lines.append(f'> **{b["label"]}** : {b["text"]}' if b['label'] else f'> {b["text"]}')
        elif kind == 'list':
            lines.extend(f'• {i}' for i in b['items'])
        elif kind == 'steps':
            lines.extend(f'**{n}.** {i}' for n, i in enumerate(b['items'], 1))
        elif kind == 'tip':
            lines.append(f'💡 {b["text"]}')
        elif kind == 'warning':
            lines.append(f'⚠️ **{b["text"]}**')
        elif kind == 'question':
            lines.append(f'❓ **{b["text"]}**')
        elif kind == 'text':
            lines.append(b['text'])
    return '\n'.join(lines).strip()


def embed(blocks: list[dict], title: str | None = None, footer: str | None = None) -> discord.Embed:
    """Embed Discord : titre, description ordonnée, encarts et chiffres en champs."""
    color = next((COLORS.get(b['text']) for b in blocks if b['type'] == 'color' and COLORS.get(b['text'])), DEFAULT_COLOR)
    heading = next((b['text'] for b in blocks if b['type'] == 'title'), None) or title
    result = discord.Embed(title=(heading or None) and heading[:256], color=color)
    description: list[str] = []
    fields = 0
    for b in blocks:
        kind = b['type']
        if kind in ('title', 'color'):
            continue
        if kind in ('box', 'stat') and fields < 25:
            name = b['label'] or ('📌 À retenir' if kind == 'box' else 'Chiffre')
            result.add_field(name=(('📌 ' if kind == 'box' and b['label'] else '') + name)[:256],
                             value=b['text'][:1024], inline=kind == 'stat')
            fields += 1
            continue
        part = plain([b])
        if part:
            description.append(part)
    text = '\n\n'.join(description)
    if len(text) > 4000:
        text = text[:3990].rsplit(' ', 1)[0] + '…'
    result.description = text or (None if heading or fields else '…')
    if footer:
        result.set_footer(text=footer[:2048])
    return result


def render(answer: str, title: str | None = None, footer: str | None = None) -> discord.Embed:
    blocks = parse(answer)
    if not blocks:
        blocks = [{'type': 'text', 'text': str(answer or '').strip()[:3900] or '…'}]
    return embed(blocks, title, footer)
