# MyProspectAgent — configurateur web

Application **statique** (Astro + Tailwind) qui aide à générer un `prospect.config.json` pour
l'agent. **100 % côté navigateur, zéro backend, aucune clé API demandée** — la config est produite
localement, puis :

- copiée comme commande courte : `mpa init --b64 <code>`, ou
- téléchargée comme `prospect.config.json` (puis `mpa init prospect.config.json`).

## Dev / build

```bash
npm install
npm run dev       # http://localhost:4321
npm run build     # sortie statique dans dist/
```

## Déploiement (GitHub Pages / Vercel)

Sortie 100 % statique (`output: 'static'`). Sur GitHub Pages (project site servi sous
`/<repo>/`), définir `PAGES_BASE=/myprospectagent` au build ; en local / sur Vercel, laisser vide
(`base '/'`).

Le schéma émis doit rester aligné avec `prospect/config.py` (le contrat partagé).
