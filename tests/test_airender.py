import unittest

from rene import airender

ANSWER = """[TITRE] Ton code cadeau
[TEXTE] Ton code n'est pas encore activé.
Il le sera après le grattage.
[ENCARD] (le jeudi : 18 h)
[CHIFFRE] Messages : 1 240
[CHIFFRE] Membres actifs : 87
[ETAPES] Ouvre le lien | Gratte la carte | Entre le code
[LISTE]
- PointNemo
- ChristmasRun
[ASTUCE] Garde ta capture.
[ATTENTION] Le code expire en 24 h.
[QUESTION] Tu as reçu le MP ?
[COULEUR] vert"""


class AiRenderTest(unittest.TestCase):
    def test_tags_become_blocks(self):
        blocks = airender.parse(ANSWER)
        kinds = [b['type'] for b in blocks]
        self.assertEqual(kinds, ['title', 'text', 'box', 'stat', 'stat', 'steps', 'list', 'tip', 'warning', 'question', 'color'])
        self.assertEqual(blocks[1]['text'], "Ton code n'est pas encore activé.\nIl le sera après le grattage.")
        self.assertEqual((blocks[2]['label'], blocks[2]['text']), ('le jeudi', '18 h'))
        self.assertEqual(blocks[5]['items'], ['Ouvre le lien', 'Gratte la carte', 'Entre le code'])
        self.assertEqual(blocks[6]['items'], ['PointNemo', 'ChristmasRun'])

    def test_embed_layout(self):
        embed = airender.render(ANSWER, footer='René')
        self.assertEqual(embed.title, 'Ton code cadeau')
        self.assertEqual(embed.color.value, airender.COLORS['vert'])
        self.assertEqual([f.name for f in embed.fields], ['📌 le jeudi', 'Messages', 'Membres actifs'])
        self.assertEqual([f.inline for f in embed.fields], [False, True, True])
        self.assertIn('**1.** Ouvre le lien', embed.description)
        self.assertIn('⚠️ **Le code expire en 24 h.**', embed.description)
        self.assertNotIn('[', embed.description)

    def test_answer_without_tags_stays_readable(self):
        embed = airender.render('## Bonjour\n\nVoici **une** réponse.\n\nDeuxième paragraphe.')
        self.assertEqual(embed.description, 'Bonjour\n\nVoici une réponse.\n\nDeuxième paragraphe.')
        self.assertIsNone(embed.title)
        self.assertEqual(airender.render('').description, '…')

    def test_tags_on_a_single_line_or_escaped(self):
        # ChatGPT transforme les retours à la ligne simples en espaces : tout arrive sur une ligne.
        one_line = ('[TITRE] Bilan du mois [TEXTE] Tout va bien. [CHIFFRE] Messages : 1 240 '
                    r'**[ENCART]** Le jeudi : 18 h \[ETAPES\] Sondage | Event [QUESTION] On lance ?')
        blocks = airender.parse(one_line)
        self.assertEqual([b['type'] for b in blocks], ['title', 'text', 'stat', 'box', 'steps', 'question'])
        self.assertEqual(blocks[0]['text'], 'Bilan du mois')
        self.assertEqual((blocks[3]['label'], blocks[3]['text']), ('Le jeudi', '18 h'))
        self.assertEqual(blocks[4]['items'], ['Sondage', 'Event'])
        # Un crochet ordinaire n'est pas une balise.
        self.assertEqual(airender.parse('Voir [ici] pour plus')[0]['text'], 'Voir [ici] pour plus')

    def test_pre_prompt_lists_every_tag(self):
        text = airender.pre_prompt(700)
        for tag in ('[TITRE]', '[TEXTE]', '[ENCART]', '[CHIFFRE]', '[LISTE]', '[ETAPES]', '[QUESTION]'):
            self.assertIn(tag, text)
        self.assertIn('700 caractères', text)


if __name__ == '__main__':
    unittest.main()
