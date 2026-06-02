# MyProspectAgent

> **Agent de prospection freelance, open-source et local-first.** Décris ton client idéal une
> fois ; l'agent trouve des entreprises correspondantes, score chaque prospect sur 100, extrait un
> contact, explique pourquoi ça matche, et rédige un email de prospection — le tout sur **ta**
> machine avec **ton** LLM. Rien n'est envoyé à un backend hébergé.

🔗 **Configurateur en ligne (zéro backend)** : https://nathan-pichon.github.io/MyProspectAgent/

CLI : **`mpa`** · Package Python : `prospect` · LLM par défaut : **Ollama / `gemma4:e2b`** (tourne
sur une petite machine), branchable sur un modèle plus puissant ou cloud.

---

## Ce que ça fait

Tu donnes un **objectif en langage naturel**, par exemple :

> _« Trouver des startups SaaS qui utilisent MongoDB et qui pourraient vouloir un audit de
> performance MongoDB. »_

L'agent :

1. **Scout** — génère des requêtes de recherche pour trouver des entreprises (web, job boards qui
   révèlent la stack, annuaires, LinkedIn en opt-in).
2. **Trieur** — écarte le bruit (articles, comparatifs, pages produit d'un éditeur) pour ne garder
   que des pages d'entreprise identifiables.
3. **Contacts** — extrait (en déterministe, sans LLM) un email — classé _named / role / generic_ —,
   une page LinkedIn, le site.
4. **Qualifier** — score le prospect sur 100 avec une grille explicable
   (**Signal 40 · Besoin 25 · ICP 20 · Joignabilité 15**) et **cite les preuves textuelles** du
   signal. Garde-fou anti-hallucination : une preuve qui n'existe pas dans la page est rejetée.
5. **Outreacher** — rédige un email de prospection français personnalisé (il **rédige seulement,
   n'envoie jamais**).

Les résultats apparaissent dans un **dashboard local** : carte par prospect (score + détail,
preuves vérifiables, contact, email éditable), **funnel Kanban** (drag & drop), section _why-not_,
et une métrique de résultat : _prospects prêts à contacter (contact + email rédigé)_.

## Installation & lancement

```bash
python3 -m venv .venv && source .venv/bin/activate     # Python >= 3.11
pip install -e '.[scrape,dev]'
playwright install chromium                             # une seule fois
ollama serve & ollama pull gemma4:e2b                   # LLM local (défaut)

mpa init --seed      # écrit un prospect.config.json d'exemple
mpa doctor           # checklist environnement (+ rappel d'usage responsable)
mpa goal "clients utilisant MongoDB, intéressés par un audit"   # définit l'objectif
mpa run              # une recherche (ajoute --max-steps 15 pour un test rapide)
mpa dashboard        # dashboard local sur http://127.0.0.1:4321
pytest -q            # tests (offline, sans LLM)
python -m eval.run   # GATE qualité du Qualifier (précision/recall)
```

### Configurer via le web (sans backend)

Le dossier [`web/`](web/) est un **configurateur statique** (Astro + Tailwind, zéro backend, ne
collecte aucune clé). Il génère un `prospect.config.json` (commande `mpa init --b64 <code>` ou
téléchargement). `cd web && npm install && npm run dev`.

## Brancher un LLM plus puissant / cloud

Tout passe par `llm` dans `prospect.config.json`. Deux options :

- **Remplacer** le modèle : `provider` = `ollama` | `openai` | `anthropic` | `lmstudio` |
  `mistral` | `groq`, et `model`.
- **Routage à deux niveaux** (recommandé) : garder le petit modèle local pour Scout/Trieur (volume)
  et un modèle fort pour le Qualifier/Outreacher (qualité) via `strong_provider` / `strong_model`.

Les **clés API restent locales** (variable d'env `PROSPECT_LLM_API_KEY` /
`PROSPECT_STRONG_LLM_API_KEY`, ou le panneau ⚙ du dashboard). Elles ne sont **jamais** mises dans
la config partagée ni demandées sur le web.

## Architecture (résumé)

| Module | Rôle |
|---|---|
| `prospect/config.py` | Schéma Pydantic partagé (`Offering`, `ICP`, `goal`, `Outreach`, `LLMConfig` two-tier, …) |
| `prospect/llm/` | Couche LLM (Ollama, OpenAI-compat, Anthropic) + routage light/strong |
| `prospect/sources/` | Sources : `web_search`, `rss`, `linkedin` (opt-in), `directories` |
| `prospect/engine/` | `scout`, `trieur`, `contacts`, `qualifier`, `outreacher`, `loop`, `scrapers`, `filters` |
| `prospect/store/` | SQLite local (`prospect.db`) : prospects, funnel, why-not, feedback |
| `prospect/server.py` + `dashboard/` | Serveur 127.0.0.1 + dashboard HTML autonome |
| `web/` | Configurateur statique (Astro) |
| `eval/` | GATE qualité du Qualifier (précision ≥ 0.70) |

## ⚖️ Usage responsable

- L'agent **rédige** les emails, il ne les **envoie jamais** — tu envoies depuis ton propre client
  mail (lien `mailto:` pré-rempli).
- N'utilise que des **contacts publics**. Respecte le **RGPD** et les opt-out — pas de spam.
- La source **LinkedIn est opt-in** : à toi de respecter les conditions d'utilisation de LinkedIn.

## Licence

AGPL-3.0-or-later. Voir [LICENSE](LICENSE).
